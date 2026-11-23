from datetime import datetime
from unittest.mock import Mock

import pytest

from app.campaigns.scheduling import DailySendWindow, schedule_after_email_open
from app.config import get_settings
from scripts import cron_worker, run_opened_campaign
from scripts.run_opened_campaign import OpenedRunResult


def at(value: str) -> datetime:
    return datetime.fromisoformat(value)


@pytest.mark.parametrize(("opened", "scheduled"), [
    ("2026-11-17T09:00:00-03:00", "2026-11-18T14:00:00-03:00"),
    ("2026-11-17T23:50:00-03:00", "2026-11-18T14:00:00-03:00"),
    ("2026-11-18T00:10:00-03:00", "2026-11-19T14:00:00-03:00"),
    ("2026-11-18T02:50:00+00:00", "2026-11-18T14:00:00-03:00"),
    ("2026-11-18T03:10:00+00:00", "2026-11-19T14:00:00-03:00"),
    ("2026-11-20T10:00:00-03:00", "2026-11-21T14:00:00-03:00"),
    ("2026-12-31T23:50:00-03:00", "2027-01-01T14:00:00-03:00"),
])
def test_opening_schedules_next_local_calendar_day(opened, scheduled):
    assert schedule_after_email_open(at(opened)) == at(scheduled)


def test_naive_opening_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        schedule_after_email_open(datetime(2026, 11, 17, 10))


def test_invalid_send_time_fails_before_startup(monkeypatch):
    monkeypatch.setenv("WHATSAPP_SEND_TIME", "25:00")
    get_settings.cache_clear()
    with pytest.raises(ValueError):
        get_settings()


def test_legacy_empty_schedule_limit_uses_a_valid_default(monkeypatch):
    monkeypatch.setenv("WHATSAPP_SCHEDULE_LIMIT", "")
    get_settings.cache_clear()
    assert get_settings().whatsapp_schedule_limit == 500


def test_window_opens_at_14_and_continues_for_spaced_messages():
    window = DailySendWindow()
    assert not window.is_open(at("2026-11-18T13:59:59-03:00"))
    assert window.is_open(at("2026-11-18T17:00:00+00:00"))
    assert window.is_open(at("2026-11-18T14:01:00-03:00"))
    assert window.is_open(at("2026-11-18T15:00:00-03:00"))
    assert not window.is_open(at("2026-11-19T00:00:00-03:00"))
    assert not window.is_open(at("2026-11-19T13:59:59-03:00"))


def test_restart_after_14_waits_until_next_daily_start():
    window = DailySendWindow()
    assert not window.is_open(at("2026-11-18T14:01:00-03:00"))
    assert not window.is_open(at("2026-11-18T18:00:00-03:00"))
    assert window.is_open(at("2026-11-19T14:00:20-03:00"))


def test_outage_does_not_reopen_the_same_window():
    window = DailySendWindow()
    assert window.is_open(at("2026-11-18T14:00:10-03:00"))
    window.suspend(at("2026-11-18T14:00:15-03:00"))
    assert not window.is_open(at("2026-11-18T14:00:20-03:00"))
    assert not window.is_open(at("2026-11-18T16:00:00-03:00"))
    assert window.is_open(at("2026-11-19T14:00:00-03:00"))


def test_morning_failure_does_not_cancel_afternoon_window():
    window = DailySendWindow()
    window.suspend(at("2026-11-18T10:00:00-03:00"))
    assert window.is_open(at("2026-11-18T14:00:00-03:00"))


@pytest.fixture
def discovery(monkeypatch):
    source, campaigns, history = Mock(), Mock(), Mock()
    campaigns.find.return_value = {"id": 42}
    campaigns.create.return_value = {"id": 42}
    history.reserve.return_value = 100
    source.list_opened_since.return_value = [{
        "source_id": 1, "lead_key": "b9000000-0000-0000-0000-000000000001",
        "telefone_contato": "5531999999999", "nome_decisor": "Ana",
        "empresa": "Loja", "lote_key": None,
        "primeira_abertura": at("2026-11-17T20:00:00-03:00"),
        "ultima_abertura": at("2026-11-20T10:00:00-03:00"),
    }]
    for name, value in {
        "WhatsAppLeadRepository": source, "CampaignRepository": campaigns,
        "MessageHistoryRepository": history,
    }.items():
        monkeypatch.setattr(run_opened_campaign, name, lambda value=value: value)
    return source, campaigns, history


def test_discovery_snapshots_first_opening_even_after_repeated_opens(discovery):
    source, _, history = discovery
    now = at("2026-11-20T12:00:00-03:00")
    result = run_opened_campaign.schedule_opened_email_campaign(get_settings(), now)
    assert result.reserved == 1
    row, campaign_name = history.reserve.call_args.args
    assert campaign_name == "Campanha 2"
    assert row["email_opened_at"] == at("2026-11-17T20:00:00-03:00")
    assert row["scheduled_at"] == at("2026-11-18T14:00:00-03:00")
    assert "Ana" in row["message"]
    assert row["source_id"] == 1
    source.list_opened_since.assert_called_once_with(
        opened_from=at("2026-11-17T00:00:00-03:00"), as_of=now,
        campaign_name="Campanha 2", limit=500,
    )


def test_dry_run_reads_candidates_without_creating_records(discovery):
    _, campaigns, history = discovery
    campaigns.find.return_value = None
    result = run_opened_campaign.schedule_opened_email_campaign(
        get_settings(), at("2026-11-17T21:00:00-03:00"), dry_run=True,
    )
    assert result.eligible == 1 and result.reserved == 0 and result.dry_run
    campaigns.create.assert_not_called()
    campaigns.update_status.assert_not_called()
    history.reserve.assert_not_called()


def test_missing_message_configuration_stops_before_database_access(discovery):
    source, campaigns, history = discovery
    settings = get_settings().model_copy(update={"whatsapp_campaign_name": ""})
    with pytest.raises(RuntimeError, match="WHATSAPP_CAMPAIGN_NAME"):
        run_opened_campaign.schedule_opened_email_campaign(
            settings, at("2026-11-17T21:00:00-03:00"),
        )
    source.list_opened_since.assert_not_called()
    campaigns.find.assert_not_called()
    history.reserve.assert_not_called()


def test_first_eligible_contact_creates_automatic_campaign(discovery):
    _, campaigns, _ = discovery
    campaigns.find.return_value = None
    result = run_opened_campaign.schedule_opened_email_campaign(
        get_settings(), at("2026-11-17T21:00:00-03:00"),
    )
    assert result.campaign_id == 42
    assert campaigns.create.call_args.kwargs["lote"] == "automatico"


def test_no_new_contacts_keeps_existing_campaign_available_for_dispatch(discovery):
    source, campaigns, history = discovery
    source.list_opened_since.return_value = []
    result = run_opened_campaign.schedule_opened_email_campaign(
        get_settings(), at("2026-11-18T14:00:00-03:00"),
    )
    assert result.campaign_id == 42 and result.reserved == 0
    campaigns.create.assert_not_called()
    history.reserve.assert_not_called()


def test_conflicting_reservation_does_not_count_as_another_message(discovery):
    _, _, history = discovery
    history.reserve.return_value = None
    result = run_opened_campaign.schedule_opened_email_campaign(
        get_settings(), at("2026-11-18T14:00:00-03:00"),
    )
    assert result.reserved == 0


@pytest.fixture
def worker(monkeypatch):
    discover = Mock(return_value=OpenedRunResult(42, 0, 0, False))
    dispatch = Mock(return_value=1)
    monkeypatch.setattr(cron_worker, "schedule_opened_email_campaign", discover)
    monkeypatch.setattr(cron_worker, "dispatch_campaign_messages", dispatch)
    return discover, dispatch


def test_worker_reserves_before_14_without_accessing_redis(worker):
    discover, dispatch = worker
    assert cron_worker.run_worker_cycle(
        get_settings(), DailySendWindow(), at("2026-11-18T13:00:00-03:00"),
    ) == 0
    discover.assert_called_once()
    dispatch.assert_not_called()


def test_worker_limits_dispatch_to_the_current_local_day(worker):
    _, dispatch = worker
    assert cron_worker.run_worker_cycle(
        get_settings(), DailySendWindow(), at("2026-11-18T14:00:00-03:00"),
    ) == 1
    dispatch.assert_called_once_with(
        batch_size=1, campaign_id=42, dispatch_until=at("2026-11-19T00:00:00-03:00"),
        reserved_before=at("2026-11-18T14:01:00-03:00"),
    )


def test_dry_run_worker_cannot_dispatch_even_at_14(worker):
    discover, dispatch = worker
    settings = get_settings().model_copy(update={"whatsapp_schedule_dry_run": True})
    assert cron_worker.run_worker_cycle(
        settings, DailySendWindow(), at("2026-11-18T14:00:00-03:00"),
    ) == 0
    assert discover.call_args.kwargs["dry_run"] is True
    dispatch.assert_not_called()


def test_disabled_worker_does_not_schedule_or_dispatch(worker):
    discover, dispatch = worker
    settings = get_settings().model_copy(update={"whatsapp_schedule_enabled": False})
    assert cron_worker.run_worker_cycle(
        settings, DailySendWindow(), at("2026-11-18T14:00:00-03:00"),
    ) == 0
    discover.assert_not_called()
    dispatch.assert_not_called()


def test_failed_cycle_resumes_only_at_next_14(worker):
    _, dispatch = worker
    window = DailySendWindow()
    dispatch.side_effect = ConnectionError("Redis unavailable")
    with pytest.raises(ConnectionError):
        cron_worker.run_worker_cycle(get_settings(), window, at("2026-11-18T14:00:00-03:00"))
    dispatch.side_effect = None
    dispatch.return_value = 1
    dispatch.reset_mock()
    assert cron_worker.run_worker_cycle(get_settings(), window, at("2026-11-18T15:00:00-03:00")) == 0
    dispatch.assert_not_called()
    assert cron_worker.run_worker_cycle(get_settings(), window, at("2026-11-19T14:00:00-03:00")) == 1


def test_worker_wakes_at_14_instead_of_sleeping_past_start():
    assert cron_worker.seconds_until_next_cycle(get_settings(), at("2026-11-18T13:59:45-03:00")) == 15
    assert cron_worker.seconds_until_next_cycle(get_settings(), at("2026-11-18T14:02:00-03:00")) == 60
