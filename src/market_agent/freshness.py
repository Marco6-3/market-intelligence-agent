from __future__ import annotations

from datetime import date, datetime, timezone

from .models import FreshnessInfo, FreshnessLabel
from .utils.text import clean_text


def classify_freshness(
    published_at: str | None,
    report_date: date,
    *,
    newly_discovered: bool = False,
) -> FreshnessInfo:
    published_date = parse_date(published_at)
    if published_date is None:
        return FreshnessInfo(
            published_days_ago=None,
            is_newly_published=False,
            is_newly_discovered=newly_discovered,
            freshness_label="unknown",
        )
    age_days = (report_date - published_date).days
    if age_days <= 3:
        label: FreshnessLabel = "fresh"
    elif age_days <= 14:
        label = "recent"
    else:
        label = "stale_context"
    return FreshnessInfo(
        published_days_ago=age_days,
        is_newly_published=label in {"fresh", "recent"},
        is_newly_discovered=newly_discovered,
        freshness_label=label,
    )


def parse_date(value: str | None) -> date | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed.date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def freshness_label(value: FreshnessInfo | str | None) -> FreshnessLabel:
    if isinstance(value, FreshnessInfo):
        return value.freshness_label
    if value in {"fresh", "recent", "stale_context", "unknown"}:
        return value  # type: ignore[return-value]
    if value in {"stale", "background"}:
        return "stale_context"
    return "unknown"
