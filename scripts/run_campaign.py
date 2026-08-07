import argparse

import _path  # noqa: F401
from app.config import get_settings
from app.utils.logging import configure_logging
from app.whatsapp.dispatcher import dispatch_campaign_messages


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dispatch pending WhatsApp messages.")
    parser.add_argument("--campaign-id", required=False, type=int)
    parser.add_argument("--batch-size", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    configure_logging()
    args = parse_args()
    settings = get_settings()
    sent_count = dispatch_campaign_messages(
        batch_size=args.batch_size or settings.default_batch_size,
        campaign_id=args.campaign_id,
    )
    print(f"Sent messages: {sent_count}")


if __name__ == "__main__":
    main()
