from app.campaigns.queue_builder import build_queue_rows
from app.campaigns.templates import (
    find_campaign_image_path,
    render_template,
    shorten_marketing_links,
)
from app.whatsapp.evolution_client import build_text_payload


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


def test_campaign_1_has_feed_image_path() -> None:
    assert find_campaign_image_path("Campanha 1") == "campanhas/imagens/Campanha 1.png"


def test_queue_rows_include_campaign_image_path() -> None:
    rows = build_queue_rows(
        campaign_id=1,
        leads=[
            {
                "lead_key": "lead-1",
                "decisor": "Hugo",
                "whatsapp_contato1": "5531999999999",
            }
        ],
        message_template="Olá {{decisor}}",
        image_path="campanhas/imagens/Campanha 1.png",
    )

    assert rows[0]["image_path"] == "campanhas/imagens/Campanha 1.png"
