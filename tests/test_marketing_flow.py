from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import UUID

import httpx
import pytest

from app.campaigns import scheduler
from app.campaigns.queue_builder import build_queue_rows
from app.campaigns.templates import render_template
from app.leads.normalization import normalize_phone
from app.leads.segmentation import filter_eligible_leads
from app.whatsapp import dispatcher
from scripts.create_operational_tables import build_statements, main as prepare_tables


LEAD_KEY = UUID("b9000000-0000-0000-0000-000000000001")


def lead(source_id=10, phone="(31) 99999-9999"):
    return {
        "source_id": source_id, "lead_key": LEAD_KEY, "nome_decisor": "Ana",
        "empresa": "Loja A", "telefone_contato": phone, "lote_key": "lote1",
    }


@pytest.mark.parametrize(("raw", "expected"), [
    ("(31) 99999-9999", "5531999999999"),
    ("+55 31 99999-9999", "5531999999999"),
    ("(55) 99999-9999", "5555999999999"),
    ("(31) 3333-3333", "553133333333"),
    ("", ""), ("123", ""), ("abc", ""),
])
def test_phone_normalization(raw, expected):
    assert normalize_phone(raw) == expected


def test_duplicate_source_events_result_in_one_contact():
    selected = filter_eligible_leads([
        lead(10), lead(11, "+55 31 99999-9999"), lead(12, "inválido"),
    ])
    assert [row["source_id"] for row in selected] == [10]


def test_existing_templates_accept_native_marketing_columns():
    assert render_template("Olá {{decisor}} da {{empresa}} ({{lote}})", lead()) == "Olá Ana da Loja A (lote1)"
    rows = build_queue_rows(1, [lead()], "Olá {{nome_decisor}}")
    assert rows[0]["message"] == "Olá Ana"
    assert rows[0]["phone"] == "5531999999999"
    assert rows[0]["lead_key"] == str(LEAD_KEY)
    assert rows[0]["source_id"] == 10


@pytest.fixture
def campaign_dependencies(monkeypatch):
    campaigns = Mock()
    campaigns.get.return_value = {"id": 1, "name": "Campanha 2", "lote": "lote1", "message_template": "Olá {{decisor}}"}
    leads = Mock()
    history = Mock()
    history.list_campaign_phones.return_value = set()
    history.reserve.return_value = 100
    queue = Mock()
    queue.enqueue_many.side_effect = lambda rows: len(rows)
    for name, value in {
        "CampaignRepository": campaigns, "WhatsAppLeadRepository": leads,
        "MessageHistoryRepository": history, "RedisMessageQueue": queue,
    }.items():
        monkeypatch.setattr(scheduler, name, lambda value=value: value)
    return leads, history, queue


def test_scheduler_applies_limit_after_deduplication_and_previous_sends(campaign_dependencies):
    leads, history, queue = campaign_dependencies
    leads.list_by_lote.return_value = [
        lead(10), lead(11), lead(12, "(31) 98888-8888"), lead(13, "(31) 97777-7777"),
    ]
    history.list_campaign_phones.return_value = {"5531999999999"}
    assert scheduler.create_campaign_queue(1, limit=1) == 1
    rows = queue.enqueue_many.call_args.args[0]
    assert len(rows) == 1
    assert rows[0]["source_id"] == 12
    assert rows[0]["history_id"] == 100
    assert rows[0]["message"] == "Olá Ana"
    history.list_campaign_phones.assert_called_once_with("Campanha 2")


def test_concurrent_reservation_does_not_enqueue_a_second_send(campaign_dependencies):
    leads, history, queue = campaign_dependencies
    leads.list_by_lote.return_value = [lead()]
    history.reserve.return_value = None
    assert scheduler.create_campaign_queue(1) == 0
    queue.enqueue_many.assert_called_once_with([])


def test_pending_reservation_survives_enqueue_failure(campaign_dependencies):
    leads, history, queue = campaign_dependencies
    leads.list_by_lote.return_value = [lead()]
    queue.enqueue_many.side_effect = ConnectionError("Redis unavailable")
    with pytest.raises(ConnectionError):
        scheduler.create_campaign_queue(1)
    history.reserve.assert_called_once()


def test_table_preparation_preserves_source_and_source_independent_history():
    statements = "\n".join(statement.as_string() for statement in build_statements("mkt_novauniao"))
    assert "whatsapp_historico" in statements
    assert "unique (campaign_name, phone)" in statements
    assert "source_id bigint not null" in statements
    assert "lead_key uuid not null" in statements
    assert "whatsapp_marketing" not in statements
    assert "whatsapp_mkt" not in statements
    assert "drop " not in statements.lower()
    assert "trigger" not in statements.lower()


def test_table_dry_run_never_connects(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["create_operational_tables.py", "--dry-run"])
    prepare_tables()
    assert "create table if not exists" in capsys.readouterr().out


@pytest.fixture
def dispatch_dependencies(monkeypatch):
    queue, history, opt_outs, client = Mock(), Mock(), Mock(), Mock()
    history.list_pending.return_value = []
    history.claim.return_value = {"id": 100, "attempts": 1}
    opt_outs.is_opted_out.return_value = False
    client.send_text.return_value = {"key": {"id": "provider-1"}}
    client.send_image.return_value = {"key": {"id": "provider-image"}}
    queue.list_pending.return_value = [{
        "id": "history:100", "history_id": 100, "source_id": 10,
        "campaign_id": 1, "lead_key": str(LEAD_KEY), "phone": "5531999999999",
        "message": "Olá Ana", "image_path": "", "attempts": 0,
        "provider_response": None,
    }]
    factory = Mock(return_value=client)
    monkeypatch.setattr(dispatcher, "RedisMessageQueue", lambda: queue)
    monkeypatch.setattr(dispatcher, "MessageHistoryRepository", lambda: history)
    monkeypatch.setattr(dispatcher, "OptOutRepository", lambda: opt_outs)
    monkeypatch.setattr(dispatcher, "EvolutionClient", factory)
    return queue, history, opt_outs, client, factory


def test_success_records_provider_id_and_date_before_queue_ack(dispatch_dependencies):
    queue, history, _, client, _ = dispatch_dependencies
    operations = Mock()
    operations.attach_mock(history.claim, "claim")
    operations.attach_mock(client.send_text, "send")
    operations.attach_mock(history.mark_sent, "save")
    operations.attach_mock(queue.mark_sent, "ack")
    assert dispatcher.dispatch_campaign_messages(batch_size=1) == 1
    assert [call[0] for call in operations.mock_calls] == ["claim", "send", "save", "ack"]
    args = history.mark_sent.call_args.args
    assert args[:2] == (100, {"key": {"id": "provider-1"}})
    assert isinstance(args[2], datetime) and args[2].tzinfo is not None


def test_image_uses_caption_and_same_history(dispatch_dependencies):
    queue, history, _, client, _ = dispatch_dependencies
    queue.list_pending.return_value[0]["image_path"] = "tests/fixtures/campaign.png"
    assert dispatcher.dispatch_campaign_messages(batch_size=1) == 1
    client.send_image.assert_called_once_with(
        phone="5531999999999", image_path="tests/fixtures/campaign.png", caption="Olá Ana",
    )
    client.send_text.assert_not_called()
    history.mark_sent.assert_called_once()


def test_database_failure_before_claim_stops_provider_call(dispatch_dependencies):
    _, history, _, _, factory = dispatch_dependencies
    history.claim.side_effect = ConnectionError("Database unavailable")
    with pytest.raises(ConnectionError):
        dispatcher.dispatch_campaign_messages(batch_size=1)
    factory.assert_not_called()


def test_opted_out_contact_is_cancelled_without_send(dispatch_dependencies):
    queue, history, opt_outs, _, factory = dispatch_dependencies
    opt_outs.is_opted_out.return_value = True
    assert dispatcher.dispatch_campaign_messages(batch_size=1) == 0
    history.mark_cancelled.assert_called_once()
    queue.mark_cancelled.assert_called_once()
    factory.assert_not_called()


def test_already_sent_history_is_not_sent_again(dispatch_dependencies):
    queue, history, _, _, factory = dispatch_dependencies
    history.claim.return_value = None
    history.get.return_value = {"status": "sent"}
    assert dispatcher.dispatch_campaign_messages(batch_size=1) == 0
    queue.mark_cancelled.assert_called_once()
    factory.assert_not_called()


@pytest.mark.parametrize("status", ["processing", "uncertain"])
def test_interrupted_attempt_is_not_automatically_resent(dispatch_dependencies, status):
    queue, history, _, _, factory = dispatch_dependencies
    history.claim.return_value = None
    history.get.return_value = {"status": status}
    assert dispatcher.dispatch_campaign_messages(batch_size=1) == 0
    history.expire_processing.assert_called_once()
    factory.assert_not_called()
    if status == "uncertain":
        queue.mark_cancelled.assert_called_once()
    else:
        queue.mark_cancelled.assert_not_called()


def test_timeout_requires_verification_instead_of_automatic_resend(dispatch_dependencies):
    queue, history, _, client, _ = dispatch_dependencies
    client.send_text.side_effect = httpx.ReadTimeout("Provider response lost")
    assert dispatcher.dispatch_campaign_messages(batch_size=1) == 0
    history.mark_uncertain.assert_called_once_with(100, "Provider response lost")
    history.mark_sent.assert_not_called()
    queue.mark_failed.assert_not_called()


@pytest.mark.parametrize(("attempts", "will_retry"), [(1, True), (3, False)])
def test_known_rejection_obeys_attempt_limit(dispatch_dependencies, attempts, will_retry):
    queue, history, _, client, _ = dispatch_dependencies
    history.claim.return_value = {"attempts": attempts}
    response = httpx.Response(429, request=httpx.Request("POST", "https://evolution.test"))
    client.send_text.side_effect = httpx.HTTPStatusError("Rejected", request=response.request, response=response)
    assert dispatcher.dispatch_campaign_messages(batch_size=1) == 0
    history.mark_failed.assert_called_once_with(100, "Rejected", will_retry)
    queue.mark_failed.assert_called_once()


def test_recovery_restores_durable_pending_reservations(dispatch_dependencies):
    queue, history, _, _, _ = dispatch_dependencies
    pending = [{"history_id": 100}]
    history.list_pending.return_value = pending
    queue.list_pending.return_value = []
    dispatcher.dispatch_campaign_messages(batch_size=1, campaign_id=1)
    queue.enqueue_many.assert_called_once_with(pending)
    history.list_pending.assert_called_once_with(limit=100, campaign_id=1)


def test_result_is_cached_if_database_fails_after_send(dispatch_dependencies):
    queue, history, _, client, _ = dispatch_dependencies
    history.mark_sent.side_effect = ConnectionError("Database unavailable")
    with pytest.raises(ConnectionError):
        dispatcher.dispatch_campaign_messages(batch_size=1)
    client.send_text.assert_called_once()
    queue.record_provider_response.assert_called_once()
    queue.mark_sent.assert_not_called()


def test_redis_result_cache_failure_still_persists_success(dispatch_dependencies):
    queue, history, _, client, _ = dispatch_dependencies
    queue.record_provider_response.side_effect = ConnectionError("Redis unavailable")
    assert dispatcher.dispatch_campaign_messages(batch_size=1) == 1
    client.send_text.assert_called_once()
    history.mark_sent.assert_called_once()
    queue.mark_sent.assert_called_once()


def test_dispatch_stops_when_daily_window_has_ended(dispatch_dependencies):
    _, history, _, _, factory = dispatch_dependencies
    deadline = datetime(2000, 1, 1, tzinfo=timezone.utc)
    assert dispatcher.dispatch_campaign_messages(batch_size=1, dispatch_until=deadline) == 0
    history.claim.assert_not_called()
    factory.assert_not_called()


def test_automatic_dispatch_applies_reservation_cutoff_before_sending(dispatch_dependencies):
    queue, history, _, _, factory = dispatch_dependencies
    cutoff = datetime(2026, 11, 18, 17, 1, tzinfo=timezone.utc)
    history.claim.return_value = None
    history.get.return_value = {"status": "pending"}
    assert dispatcher.dispatch_campaign_messages(batch_size=1, reserved_before=cutoff) == 0
    history.list_pending.assert_called_once_with(limit=100, campaign_id=None, reserved_before=cutoff)
    history.claim.assert_called_once_with(100, reserved_before=cutoff)
    factory.assert_not_called()
    queue.mark_cancelled.assert_called_once()


def test_cached_provider_result_is_saved_without_a_second_send(dispatch_dependencies):
    queue, history, _, _, factory = dispatch_dependencies
    accepted_at = datetime.now(timezone.utc)
    queue.list_pending.return_value[0].update({
        "provider_response": {"key": {"id": "already-accepted"}},
        "accepted_at": accepted_at.isoformat(),
    })
    assert dispatcher.dispatch_campaign_messages(batch_size=1) == 0
    history.mark_sent.assert_called_once_with(100, {"key": {"id": "already-accepted"}}, accepted_at)
    queue.mark_sent.assert_called_once()
    factory.assert_not_called()
