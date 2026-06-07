from __future__ import annotations

from datetime import date

from ..cache import FileCache
from ..models import EarningsCalendarItem, NewsItem
from ..utils.text import truncate
from ..utils.time import coerce_datetime_string, utc_now_iso

FINNHUB_SOURCE = "Finnhub"
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


class FinnhubClient:
    def __init__(self, api_key: str, cache: FileCache) -> None:
        self.api_key = api_key
        self.cache = cache

    def fetch_company_news(self, ticker: str, start_date: date, end_date: date) -> list[NewsItem]:
        url = f"{FINNHUB_BASE_URL}/company-news"
        data = self.cache.get_json(
            FINNHUB_SOURCE,
            url,
            params={
                "symbol": ticker,
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
                "token": self.api_key,
            },
        )
        if not isinstance(data, list):
            return []

        fetched_at = utc_now_iso()
        items: list[NewsItem] = []
        for row in data[:10]:
            if not isinstance(row, dict):
                continue
            title = truncate(row.get("headline"), 280)
            if not title:
                continue
            summary = truncate(row.get("summary"), 700)
            source_url = str(row.get("url") or url)
            items.append(
                NewsItem(
                    ticker=ticker,
                    title=title,
                    summary=summary or f"title_summary: {title}",
                    summary_confidence="medium" if summary else "low",
                    content_depth="article_excerpt" if summary else "headline_only",
                    publisher=truncate(row.get("source"), 120),
                    symbols=[ticker],
                    source_name=FINNHUB_SOURCE,
                    source_url=source_url,
                    final_url=source_url,
                    canonical_url=source_url,
                    canonical_url_status="resolved",
                    published_at=coerce_datetime_string(row.get("datetime")),
                    fetched_at=fetched_at,
                )
            )
        return items

    def fetch_earnings_calendar(
        self, ticker: str, start_date: date, end_date: date
    ) -> list[EarningsCalendarItem]:
        url = f"{FINNHUB_BASE_URL}/calendar/earnings"
        data = self.cache.get_json(
            FINNHUB_SOURCE,
            url,
            params={
                "symbol": ticker,
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
                "token": self.api_key,
            },
        )
        rows = data.get("earningsCalendar", []) if isinstance(data, dict) else []
        fetched_at = utc_now_iso()
        items: list[EarningsCalendarItem] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            report_date = coerce_datetime_string(row.get("date"))
            items.append(
                EarningsCalendarItem(
                    ticker=ticker,
                    report_date=report_date,
                    fiscal_date=coerce_datetime_string(row.get("year")),
                    eps_estimate=_float_or_none(row.get("epsEstimate")),
                    revenue_estimate=_float_or_none(row.get("revenueEstimate")),
                    time=truncate(row.get("hour"), 50),
                    source_name=FINNHUB_SOURCE,
                    source_url=url,
                    final_url=url,
                    published_at=report_date,
                    fetched_at=fetched_at,
                )
            )
        return items


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
