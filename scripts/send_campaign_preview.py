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

from app.campaigns.templates import find_campaign_template, render_template
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
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--campaign-number",
        type=int,
        help="Number from an existing template name, for example 2 for Campanha 2.",
    )
    selection.add_argument(
        "--all",
        action="store_true",
        help="Send every campaign template in order.",
    )
    selection.add_argument("--campaign-name", help="Exact name of the campaign template.")
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
    campaign_number: int | None,
    send_all: bool,
    campaign_name: str | None = None,
) -> list[dict[str, Any]]:
    if send_all:
        return templates

    if campaign_name is None and campaign_number is None:
        raise RuntimeError("Choose --campaign-name, --campaign-number or --all.")
    name = campaign_name if campaign_name is not None else f"Campanha {campaign_number}"
    return [find_campaign_template(name, templates)]


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
        campaign_name=args.campaign_name,
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
