import re
from typing import Any


def render_template(template: str, lead: dict[str, Any]) -> str:
    message = template
    for key, value in lead.items():
        message = message.replace(f"{{{{{key}}}}}", str(value or ""))
    return re.sub(r"\s+([!?.,:;])", r"\1", message)
