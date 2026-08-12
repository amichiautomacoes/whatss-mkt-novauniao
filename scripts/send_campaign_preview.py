import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

try:
    import _path  # noqa: F401
except ModuleNotFoundError:
    from scripts import _path  # noqa: F401

from app.campaigns.templates import render_template
from app.utils.logging import configure_logging
from app.whatsapp.evolution_client import EvolutionClient


DEFAULT_PREVIEW_PHONE = "5531994963959"
DEFAULT_DECISOR = "Hugo"


def parse_key_value(value: str) -> tuple[str, str]:
    key, separator, raw_value = value.partition("=")
    if not separator or not key.strip():
        raise argparse.ArgumentTypeError("Use key=value, for example: empresa=Loja Teste")
    return key.strip(), raw_value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send campaign template previews to the configured test phone."
    )
    parser.add_argument(
        "--campaign-number",
        type=int,
        default=1,
        help="1-based campaign number. Default: 1.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Send every campaign template in order.",
    )
    parser.add_argument(
        "--phone",
        default=DEFAULT_PREVIEW_PHONE,
        help=f"Preview phone. Default: {DEFAULT_PREVIEW_PHONE}.",
    )
    parser.add_argument(
        "--decisor",
        default=DEFAULT_DECISOR,
        help=f"Value used for {{{{decisor}}}}. Default: {DEFAULT_DECISOR}.",
    )
    parser.add_argument(
        "--templates-file",
        default="campanhas/campanhas_extraidas.json",
        help="Path to extracted campaign templates JSON.",
    )
    parser.add_argument(
        "--var",
        action="append",
        default=[],
        type=parse_key_value,
        help="Extra template variable as key=value. Can be used multiple times.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=2.0,
        help="Delay between messages when using --all. Default: 2.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print without sending.")
    parser.add_argument("--link-preview", action="store_true")
    parser.add_argument("--no-link-preview", action="store_true")
    return parser.parse_args()


def load_templates(path: Path) -> list[dict[str, Any]]:
    templates = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(templates, list):
        raise RuntimeError(f"Templates file must contain a list: {path}")
    return templates


def pick_templates(
    templates: list[dict[str, Any]],
    campaign_number: int,
    send_all: bool,
) -> list[dict[str, Any]]:
    if send_all:
        return templates

    index = campaign_number - 1
    if index < 0 or index >= len(templates):
        raise RuntimeError(
            f"Campaign number {campaign_number} not found. "
            f"Available: 1 to {len(templates)}."
        )
    return [templates[index]]


def build_test_lead(args: argparse.Namespace) -> dict[str, str]:
    lead = {
        "decisor": args.decisor,
        "empresa": "Loja Teste",
        "lead_key": "preview-manual",
    }
    lead.update(dict(args.var))
    return lead


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    configure_logging()
    args = parse_args()
    templates = pick_templates(
        load_templates(Path(args.templates_file)),
        campaign_number=args.campaign_number,
        send_all=args.all,
    )
    lead = build_test_lead(args)
    client = None if args.dry_run else EvolutionClient()

    for index, template in enumerate(templates):
        name = str(template.get("nome") or f"Campanha {index + 1}")
        message = render_template(str(template["corpo"]), lead)
        image_path = str(template.get("image_path") or "").strip()

        print(f"Campanha: {name}")
        print(f"Telefone preview: {args.phone}")
        print(f"Modo: {'DRY RUN' if args.dry_run else 'ENVIO REAL'}")
        if image_path:
            print(f"Imagem: {image_path}")
        print("--- Mensagem ---")
        print(message)
        print("----------------")

        if client is not None:
            if image_path:
                result = client.send_image(
                    phone=args.phone,
                    image_path=image_path,
                    caption=message,
                )
            else:
                result = client.send_text(
                    phone=args.phone,
                    message=message,
                    link_preview=args.link_preview and not args.no_link_preview,
                )
            print(f"Enviado: {result}")

        if index < len(templates) - 1 and not args.dry_run:
            time.sleep(args.delay_seconds)


if __name__ == "__main__":
    main()
