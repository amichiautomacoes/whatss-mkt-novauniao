from datetime import date, time

from app.scheduling.google_sheets import (
    ScheduledWhatsappCampaign,
    parse_schedule_rows,
)
from scripts.run_scheduled_campaign import get_scheduled_campaigns


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
