import argparse

import _path  # noqa: F401
from app.config import get_settings
from app.db.repositories import WhatsAppLeadRepository
from app.utils.logging import configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect WhatsApp marketing leads.")
    parser.add_argument("--lote", help="Optional lote name, like lote1.")
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    configure_logging()
    args = parse_args()
    repo = WhatsAppLeadRepository()

    if args.lote:
        settings = get_settings()
        limit = args.limit or settings.default_batch_size
        leads = repo.list_by_lote(args.lote, limit=limit)
        print(f"Leads found in {args.lote}: {len(leads)}")
        return

    for row in repo.count_by_lote():
        print(f"{row['lote']}: {row['total']}")


if __name__ == "__main__":
    main()
