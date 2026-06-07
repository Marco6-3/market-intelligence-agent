from __future__ import annotations

import io
from datetime import date

import pandas as pd

from ..cache import FileCache
from ..models import EarningsCalendarItem, NewsItem
from ..utils.text import truncate
from ..utils.time import coerce_datetime_string, utc_now_iso

ALPHA_SOURCE = "Alpha Vantage"
ALPHA_URL = "https://www.alphavantage.co/query"


class AlphaVantageClient:
    def __init__(self, api_key: str, cache: FileCache) -> None:
        self.api_key = api_key
        self.cache = cache

    def fetch_news(self, ticker: str, limit: int = 10) -> list[NewsItem]:
        data = self.cache.get_json(
            ALPHA_SOURCE,
            ALPHA_URL,
            params={
                "function": "NEWS_SENTIMENT",
                "tickers": ticker,
                "limit": limit,
                "apikey": self.api_key,
            },
        )
        feed = data.get("feed", []) if isinstance(data, dict) else []
        fetched_at = utc_now_iso()
        items: list[NewsItem] = []
        for row in feed:
            if not isinstance(row, dict):
                continue
            title = truncate(row.get("title"), 280)
            if not title:
                continue
            summary = truncate(row.get("summary"), 700)
            items.append(
                NewsItem(
                    ticker=ticker,
                    title=title,
                    summary=summary or f"title_summary: {title}",
                    summary_confidence="medium" if summary else "low",
                    publisher=truncate(row.get("source"), 120),
                    symbols=[ticker],
                    source_name=ALPHA_SOURCE,
                    source_url=str(row.get("url") or ALPHA_URL),
                    final_url=str(row.get("url") or ALPHA_URL),
                    published_at=coerce_datetime_string(row.get("time_published")),
                    fetched_at=fetched_at,
                )
            )
        return items

    def fetch_earnings_calendar(
        self, ticker: str, start_date: date, end_date: date
    ) -> list[EarningsCalendarItem]:
        csv_text = self.cache.get_text(
            ALPHA_SOURCE,
            ALPHA_URL,
            params={
                "function": "EARNINGS_CALENDAR",
                "symbol": ticker,
                "horizon": "3month",
                "apikey": self.api_key,
            },
        )
        try:
            frame = pd.read_csv(io.StringIO(csv_text))
        except pd.errors.ParserError:
            return []
        if frame.empty:
            return []

        fetched_at = utc_now_iso()
        items: list[EarningsCalendarItem] = []
        for row in frame.to_dict(orient="records"):
            report_date = coerce_datetime_string(row.get("reportDate"))
            if not report_date or not (start_date.isoformat() <= report_date[:10] <= end_date.isoformat()):
                continue
            items.append(
                EarningsCalendarItem(
                    ticker=ticker,
                    report_date=report_date,
                    fiscal_date=coerce_datetime_string(row.get("fiscalDateEnding")),
                    eps_estimate=_float_or_none(row.get("estimate")),
                    revenue_estimate=None,
                    time=None,
                    source_name=ALPHA_SOURCE,
                    source_url=ALPHA_URL,
                    final_url=ALPHA_URL,
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
