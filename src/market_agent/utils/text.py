from __future__ import annotations

import re


def clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def truncate(value: object, max_length: int = 500) -> str | None:
    text = clean_text(value)
    if text is None or len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."
