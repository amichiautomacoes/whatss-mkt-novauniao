import pytest
from urllib.parse import parse_qs, urlparse

from app.campaigns.queue_builder import build_queue_rows
from app.campaigns.templates import (
    find_campaign_template,
    load_campaign_templates,
    render_template,
    shorten_marketing_links,
)
from app.whatsapp.evolution_client import build_text_payload
from scripts.send_campaign_preview import parse_args, pick_templates


def test_render_template_shortens_instagram_and_whatsapp_links() -> None:
    template = (
        "Olá {{decisor}}!\n"
        "Confira: https://www.instagram.com/p/Dbq1A8roEjQ/?utm_source=ig_web_copy_link&igsh=abc\n"
        "WhatsApp: https://api.whatsapp.com/send/?phone=553141049383&text&type=phone_number&app_absent=0&utm_source=ig"
    )

    message = render_template(template, {"decisor": "Hugo"})

    assert "Olá Hugo!" in message
    assert "https://instagram.com/p/Dbq1A8roEjQ/" in message
    assert "https://wa.me/553141049383" in message
    assert "utm_source" not in message
    assert "api.whatsapp.com" not in message


def test_shorten_marketing_links_preserves_sentence_punctuation() -> None:
    message = shorten_marketing_links(
        "Veja (https://www.instagram.com/p/DbECswWoPkq/?utm_source=ig)."
    )

    assert message == "Veja (https://instagram.com/p/DbECswWoPkq/)."


def test_text_payload_disables_link_preview_by_default() -> None:
    payload = build_text_payload(
        "5531999999999",
        "Veja https://www.instagram.com/p/DbECswWoPkq/?utm_source=ig",
    )

    assert payload["linkPreview"] is False
    assert payload["text"] == "Veja https://instagram.com/p/DbECswWoPkq/"


@pytest.mark.parametrize("original", [
    "https://api.whatsapp.com/send/?phone=553141049383&text=Ol%C3%A1%21+Quero+um+or%C3%A7amento.&type=phone_number&app_absent=0",
    "https://wa.me/553141049383?text=Ol%C3%A1%21+Quero+um+or%C3%A7amento.&utm_source=campaign",
])
def test_whatsapp_shortening_preserves_prefilled_message(original):
    shortened = shorten_marketing_links(original)
    parsed = urlparse(shortened)
    assert parsed.netloc == "wa.me"
    assert parsed.path == "/553141049383"
    assert parse_qs(parsed.query) == {"text": ["Olá! Quero um orçamento."]}
    assert shorten_marketing_links(shortened) == shortened


def test_natal_message_reaches_provider_with_short_links_and_personalization():
    template = find_campaign_template("Natal 2026")
    rendered = render_template(template["corpo"], {"nome_decisor": "Ana"})
    payload = build_text_payload("5531999999999", rendered)
    assert "Boa tarde, Ana!" in payload["text"]
    assert template["whatsapp_url"] in payload["text"]
    assert template["products_url"] in payload["text"]
    assert not template.get("image_path")
    assert "{{" not in payload["text"]
    destination = urlparse(template["whatsapp_destination_url"])
    assert parse_qs(destination.query)["text"][0] == (
        "Olá! Quero um orçamento de etiquetas ou tags. Posso enviar a medida, "
        "a quantidade e o modelo da impressora."
    )


def test_removed_campaign_cannot_be_selected() -> None:
    with pytest.raises(RuntimeError, match="Template nao encontrado"):
        find_campaign_template("Campanha 1", load_campaign_templates())


def test_preview_does_not_replace_removed_number_with_another_campaign():
    templates = load_campaign_templates()
    with pytest.raises(RuntimeError, match="Template nao encontrado"):
        pick_templates(templates, campaign_number=1, send_all=False)
    assert pick_templates(templates, campaign_number=2, send_all=False)[0]["nome"] == "Campanha 2"


def test_preview_accepts_an_explicit_campaign_name():
    selected = pick_templates(
        load_campaign_templates(), campaign_number=None, send_all=False, campaign_name="Campanha 2",
    )
    assert [template["nome"] for template in selected] == ["Campanha 2"]


def test_preview_requires_explicit_campaign_selection(monkeypatch):
    monkeypatch.setattr("sys.argv", ["send_campaign_preview.py", "--dry-run"])
    with pytest.raises(SystemExit) as error:
        parse_args()
    assert error.value.code == 2


def test_queue_rows_include_campaign_image_path() -> None:
    rows = build_queue_rows(
        campaign_id=1,
        leads=[
            {
                "lead_key": "lead-1",
                "source_id": 1,
                "nome_decisor": "Hugo",
                "telefone_contato": "5531999999999",
            }
        ],
        message_template="Olá {{decisor}}",
        image_path="tests/fixtures/campaign.png",
    )

    assert rows[0]["image_path"] == "tests/fixtures/campaign.png"
