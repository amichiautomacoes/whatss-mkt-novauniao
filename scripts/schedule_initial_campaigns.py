import json
from datetime import date
from pathlib import Path

import _path  # noqa: F401
from app.campaigns.scheduling import build_split_schedule
from app.campaigns.scheduler import create_campaign_queue
from app.db.repositories import CampaignRepository
from app.utils.logging import configure_logging


CAMPAIGN_PLAN = [
    ("lote1", date(2026, 8, 10)),
    ("lote2", date(2026, 8, 11)),
    ("lote3", date(2026, 8, 12)),
    ("lote4", date(2026, 8, 13)),
    ("lote5", date(2026, 8, 14)),
]


def load_campaign_templates() -> list[dict]:
    path = Path("campanhas/campanhas_extraidas.json")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    configure_logging()
    templates = load_campaign_templates()
    campaign_repo = CampaignRepository()

    for index, (lote, send_date) in enumerate(CAMPAIGN_PLAN):
        template = templates[index]
        first_scheduled_at = build_split_schedule(1, send_date=send_date)[0]
        campaign = campaign_repo.create(
            name=template["nome"],
            message_template=template["corpo"],
            lote=lote,
            scheduled_at=first_scheduled_at,
        )
        queued = create_campaign_queue(
            campaign_id=campaign["id"],
            send_date=send_date,
        )
        print(
            f"{template['nome']} | {lote} | {send_date.isoformat()} | "
            f"campaign_id={campaign['id']} | queued={queued}"
        )


if __name__ == "__main__":
    main()
