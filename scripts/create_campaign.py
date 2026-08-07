import argparse

import _path  # noqa: F401
from app.db.repositories import CampaignRepository
from app.utils.logging import configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a WhatsApp campaign.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--lote", required=True, choices=["lote1", "lote2", "lote3", "lote4", "lote5"])
    parser.add_argument("--message-template", required=True)
    return parser.parse_args()


def main() -> None:
    configure_logging()
    args = parse_args()
    campaign = CampaignRepository().create(
        name=args.name,
        message_template=args.message_template,
        lote=args.lote,
    )
    print(f"Campaign created: {campaign['id']}")


if __name__ == "__main__":
    main()
