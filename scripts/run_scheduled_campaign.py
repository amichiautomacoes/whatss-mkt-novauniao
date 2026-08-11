import argparse
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import _path  # noqa: F401
except ModuleNotFoundError:
    from scripts import _path  # noqa: F401
from app.campaigns.scheduler import create_campaign_queue
from app.config import Settings, get_settings
from app.db.repositories import CampaignRepository
from app.scheduling.google_sheets import (
    ScheduledWhatsappCampaign,
    load_scheduled_campaigns,
)
from app.utils.logging import configure_logging


@dataclass(frozen=True)
class ScheduledRunResult:
    scheduled: ScheduledWhatsappCampaign
    campaign_id: int | None
    queued: int
    dry_run: bool


def parse_bool_env(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False

    raise ValueError(f"Valor booleano invalido: {value!r}")


def parse_int_env(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    return int(value)


def get_scheduled_campaigns(
    schedule: list[ScheduledWhatsappCampaign],
    run_date: date,
    run_time: time | None = None,
) -> list[ScheduledWhatsappCampaign]:
    due_campaigns = [
        scheduled for scheduled in schedule if scheduled.send_date == run_date
    ]
    if run_time is None:
        return due_campaigns
    return [
        scheduled
        for scheduled in due_campaigns
        if scheduled.send_time.hour == run_time.hour
        and scheduled.send_time.minute == run_time.minute
    ]


def parse_run_date(value: str | None, settings: Settings) -> date:
    if value:
        return date.fromisoformat(value)
    return datetime.now(ZoneInfo(settings.campaign_timezone)).date()


def parse_run_time(value: str | None, settings: Settings) -> time:
    if value:
        return time.fromisoformat(value)
    now = datetime.now(ZoneInfo(settings.campaign_timezone))
    return time(now.hour, now.minute)


def run_due_scheduled_campaigns(
    settings: Settings,
    run_date: date,
    run_time: time | None,
    limit: int | None = None,
    dry_run: bool = False,
) -> list[ScheduledRunResult]:
    schedule = load_scheduled_campaigns(settings, reference_date=run_date)
    scheduled_campaigns = get_scheduled_campaigns(
        schedule,
        run_date=run_date,
        run_time=run_time,
    )
    if not scheduled_campaigns:
        return []

    templates = _load_campaign_templates()
    campaign_repo = CampaignRepository()
    tz = ZoneInfo(settings.campaign_timezone)
    results: list[ScheduledRunResult] = []

    for scheduled_campaign in scheduled_campaigns:
        message_template = _find_template_body(templates, scheduled_campaign.campaign_name)
        row_limit = scheduled_campaign.limit or limit
        start_at = datetime.combine(
            scheduled_campaign.send_date,
            scheduled_campaign.send_time,
            tzinfo=tz,
        )

        if dry_run:
            results.append(
                ScheduledRunResult(
                    scheduled=scheduled_campaign,
                    campaign_id=None,
                    queued=0,
                    dry_run=True,
                )
            )
            continue

        campaign = campaign_repo.create(
            name=scheduled_campaign.campaign_name,
            message_template=message_template,
            lote=scheduled_campaign.lote_key,
            scheduled_at=start_at,
        )
        queued = create_campaign_queue(
            campaign_id=campaign["id"],
            limit=row_limit,
            scheduled_start_at=start_at,
            excluded_event_types=["queued", "sent"],
        )
        results.append(
            ScheduledRunResult(
                scheduled=scheduled_campaign,
                campaign_id=campaign["id"],
                queued=queued,
                dry_run=False,
            )
        )

    return results


def _load_campaign_templates() -> list[dict]:
    path = Path("campanhas/campanhas_extraidas.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _find_template_body(templates: list[dict], campaign_name: str) -> str:
    target = _normalize_lookup_key(campaign_name)
    for template in templates:
        if _normalize_lookup_key(str(template.get("nome", ""))) == target:
            return str(template["corpo"])
    raise RuntimeError(f"Template nao encontrado para {campaign_name!r}")


def _normalize_lookup_key(value: str) -> str:
    without_accents = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z0-9]", "", without_accents.lower())


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Agenda campanhas de WhatsApp a partir do Google Sheets."
    )
    parser.add_argument(
        "--run-date",
        help="Data em formato YYYY-MM-DD. Padrao: hoje no timezone da campanha.",
    )
    parser.add_argument(
        "--run-time",
        help=(
            "Horario em formato HH:MM. Padrao: hora atual. "
            "Se usar --run-date sem --run-time, confere apenas a data."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=parse_int_env(os.getenv("WHATSAPP_SCHEDULE_LIMIT"), 0) or None,
        help="Quantidade maxima caso a linha da planilha nao informe Qtd envios.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula sem criar campanha nem enfileirar mensagens.",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_false",
        dest="dry_run",
        help="Cria campanha e enfileira mensagens.",
    )
    parser.set_defaults(
        dry_run=parse_bool_env(os.getenv("WHATSAPP_SCHEDULE_DRY_RUN"), False)
    )
    return parser.parse_args()


def main() -> None:
    configure_logging()
    settings = get_settings()
    args = parse_args()
    run_date = parse_run_date(args.run_date, settings)
    run_time = parse_run_time(args.run_time, settings)
    match_time = args.run_date is None or args.run_time is not None

    results = run_due_scheduled_campaigns(
        settings=settings,
        run_date=run_date,
        run_time=run_time if match_time else None,
        limit=args.limit,
        dry_run=args.dry_run,
    )

    if not results:
        suffix = f" as {run_time.strftime('%H:%M')}" if match_time else ""
        print(f"Nenhuma campanha programada para {run_date.isoformat()}{suffix}.")
        return

    for result in results:
        scheduled = result.scheduled
        print(
            f"{scheduled.lote_key} -> {scheduled.campaign_name} "
            f"({scheduled.send_date.isoformat()} "
            f"{scheduled.send_time.strftime('%H:%M')}): "
            f"campaign_id={result.campaign_id} queued={result.queued} "
            f"dry_run={result.dry_run}"
        )


if __name__ == "__main__":
    main()
