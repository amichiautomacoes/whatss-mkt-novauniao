import argparse

import _path  # noqa: F401
from app.utils.logging import configure_logging
from app.whatsapp.evolution_client import EvolutionClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a single WhatsApp test message.")
    parser.add_argument("--phone", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--link-preview", action="store_true")
    parser.add_argument("--no-link-preview", action="store_true")
    return parser.parse_args()


def main() -> None:
    configure_logging()
    args = parse_args()
    result = EvolutionClient().send_text(
        args.phone,
        args.message,
        link_preview=args.link_preview and not args.no_link_preview,
    )
    print(result)


if __name__ == "__main__":
    main()
