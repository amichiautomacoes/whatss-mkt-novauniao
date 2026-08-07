import argparse
from datetime import date

import _path  # noqa: F401
from app.campaigns.scheduling import default_send_date
from app.campaigns.scheduler import create_campaign_queue
from app.utils.logging import configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create pending messages for a campaign.")
    parser.add_argument("--campaign-id", required=True, type=int)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--send-date",
        type=date.fromisoformat,
        default=None,
        help="Date to schedule messages, format YYYY-MM-DD. Defaults to tomorrow.",
    )
    return parser.parse_args()


def main() -> None:
    configure_logging()
    args = parse_args()
    send_date = args.send_date or default_send_date()
    inserted = create_campaign_queue(
        campaign_id=args.campaign_id,
        limit=args.limit,
        send_date=send_date,
    )
    print(f"Queued messages: {inserted}")
    print(f"Schedule date: {send_date.isoformat()}")


if __name__ == "__main__":
    main()
