from datetime import date, datetime, time
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.scheduling.google_sheets import (
    ScheduledWhatsappCampaign,
    parse_schedule_rows,
)
from scripts.run_scheduled_campaign import get_scheduled_campaigns
from scripts import run_scheduled_campaign as scheduled_runner


def test_parse_schedule_rows_maps_agenda_whatsapp_columns() -> None:
    schedule = parse_schedule_rows(
        [
            [
                "Data",
                "Dia",
                "Janela",
                "Horario inicio",
                "Campanha",
                "Lote",
                "Qtd envios",
                "Status",
                "Observacoes",
            ],
            [
                "12/08/2026",
                "Quarta-feira",
                "Manha",
                "10:00",
                "Campanha 1",
                "lote1",
                "35",
                "Agendada",
                "",
            ],
        ],
        reference_date=date(2026, 8, 11),
    )

    assert schedule == [
        ScheduledWhatsappCampaign(
            lote_key="lote1",
            send_date=date(2026, 8, 12),
            send_time=time(10, 0),
            campaign_name="Campanha 1",
            limit=35,
            status="Agendada",
        )
    ]


def test_parse_schedule_rows_ignores_inactive_statuses() -> None:
    schedule = parse_schedule_rows(
        [
            ["Data", "Horario inicio", "Campanha", "Lote", "Qtd envios", "Status"],
            ["12 ago.", "10:00", "Campanha 1", "Lote 1", "35", "Pausada"],
            ["13 ago.", "10:00", "Campanha 2", "Lote 2", "35", "Agendada"],
        ],
        reference_date=date(2026, 8, 11),
    )

    assert len(schedule) == 1
    assert schedule[0].campaign_name == "Campanha 2"


def test_get_scheduled_campaigns_filters_by_date_and_time() -> None:
    schedule = [
        ScheduledWhatsappCampaign(
            lote_key="lote1",
            send_date=date(2026, 8, 12),
            send_time=time(10, 0),
            campaign_name="Campanha 1",
            limit=35,
        )
    ]

    assert get_scheduled_campaigns(schedule, date(2026, 8, 12), time(10, 0)) == schedule
    assert get_scheduled_campaigns(schedule, date(2026, 8, 12), time(14, 0)) == []


def test_scheduled_dry_run_loads_templates_without_reserving_messages(monkeypatch):
    scheduled = ScheduledWhatsappCampaign(
        lote_key="lote1", send_date=date(2026, 11, 17), send_time=time(10),
        campaign_name="Campanha 2", limit=1,
    )
    monkeypatch.setattr(scheduled_runner, "load_scheduled_campaigns", lambda *args, **kwargs: [scheduled])
    repository = Mock()
    build_queue = Mock()
    monkeypatch.setattr(scheduled_runner, "CampaignRepository", lambda: repository)
    monkeypatch.setattr(scheduled_runner, "create_campaign_queue", build_queue)

    results = scheduled_runner.run_due_scheduled_campaigns(
        settings=get_settings(), run_date=scheduled.send_date,
        run_time=scheduled.send_time, dry_run=True,
    )

    assert len(results) == 1
    assert results[0].dry_run is True
    assert results[0].campaign_id is None
    repository.create.assert_not_called()
    build_queue.assert_not_called()


def test_scheduled_campaign_reaches_queue_with_current_template_and_timezone(monkeypatch):
    scheduled = ScheduledWhatsappCampaign(
        lote_key="lote1", send_date=date(2026, 11, 17), send_time=time(10),
        campaign_name="Campanha 2", limit=1,
    )
    monkeypatch.setattr(scheduled_runner, "load_scheduled_campaigns", lambda *args, **kwargs: [scheduled])
    repository = Mock()
    repository.create.return_value = {"id": 42}
    build_queue = Mock(return_value=1)
    monkeypatch.setattr(scheduled_runner, "CampaignRepository", lambda: repository)
    monkeypatch.setattr(scheduled_runner, "create_campaign_queue", build_queue)

    results = scheduled_runner.run_due_scheduled_campaigns(
        settings=get_settings(), run_date=scheduled.send_date,
        run_time=scheduled.send_time,
    )

    assert results[0].campaign_id == 42
    assert results[0].queued == 1
    assert "{{decisor}}" in repository.create.call_args.kwargs["message_template"]
    build_queue.assert_called_once_with(
        campaign_id=42, limit=1,
        scheduled_start_at=datetime(2026, 11, 17, 10, tzinfo=ZoneInfo("America/Sao_Paulo")),
    )
