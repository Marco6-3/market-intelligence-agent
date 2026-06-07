from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_in_timezone(timezone_name: str) -> date:
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        tz = timezone.utc
    return datetime.now(tz).date()


def parse_run_date(value: str | None, timezone_name: str) -> date:
    if not value:
        return today_in_timezone(timezone_name)
    return date.fromisoformat(value)


def coerce_datetime_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    if text.isdigit():
        try:
            return (
                datetime.fromtimestamp(int(text), tz=timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
        except (OverflowError, ValueError, OSError):
            return text

    known_formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y%m%dT%H%M%S",
    )
    for fmt in known_formats:
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt == "%Y-%m-%d":
                return parsed.date().isoformat()
            return parsed.replace(tzinfo=timezone.utc).replace(microsecond=0).isoformat().replace(
                "+00:00", "Z"
            )
        except ValueError:
            continue
    return text
