from __future__ import annotations

from datetime import date
from typing import Any

from ..cache import FileCache
from ..models import EarningsCalendarItem, MarketSnapshot, NewsItem
from ..utils.text import truncate
from ..utils.time import coerce_datetime_string, utc_now_iso

FMP_SOURCE = "Financial Modeling Prep"
FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"


class FMPClient:
    def __init__(self, api_key: str, cache: FileCache) -> None:
        self.api_key = api_key
        self.cache = cache

    def fetch_stock_news(self, ticker: str, limit: int = 10) -> list[NewsItem]:
        url = f"{FMP_BASE_URL}/stock_news"
        data = self.cache.get_json(
            FMP_SOURCE,
            url,
            params={"tickers": ticker, "limit": limit, "apikey": self.api_key},
        )
        if not isinstance(data, list):
            return []

        fetched_at = utc_now_iso()
        items: list[NewsItem] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            title = truncate(row.get("title"), 280)
            if not title:
                continue
            summary = truncate(row.get("text"), 700)
            items.append(
                NewsItem(
                    ticker=ticker,
                    title=title,
                    summary=summary or f"title_summary: {title}",
                    summary_confidence="medium" if summary else "low",
                    publisher=truncate(row.get("site"), 120),
                    symbols=[str(row.get("symbol") or ticker)],
                    source_name=FMP_SOURCE,
                    source_url=str(row.get("url") or f"{url}?tickers={ticker}"),
                    final_url=str(row.get("url") or f"{url}?tickers={ticker}"),
                    published_at=coerce_datetime_string(row.get("publishedDate")),
                    fetched_at=fetched_at,
                )
            )
        return items

    def fetch_earnings_calendar(
        self, ticker: str, start_date: date, end_date: date
    ) -> list[EarningsCalendarItem]:
        url = f"{FMP_BASE_URL}/earning_calendar"
        data = self.cache.get_json(
            FMP_SOURCE,
            url,
            params={
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
                "apikey": self.api_key,
            },
        )
        if not isinstance(data, list):
            return []

        fetched_at = utc_now_iso()
        items: list[EarningsCalendarItem] = []
        for row in data:
            if not isinstance(row, dict) or str(row.get("symbol", "")).upper() != ticker.upper():
                continue
            report_date = coerce_datetime_string(row.get("date"))
            items.append(
                EarningsCalendarItem(
                    ticker=ticker,
                    report_date=report_date,
                    fiscal_date=coerce_datetime_string(row.get("fiscalDateEnding")),
                    eps_estimate=_float_or_none(row.get("epsEstimated")),
                    revenue_estimate=_float_or_none(row.get("revenueEstimated")),
                    time=truncate(row.get("time"), 50),
                    source_name=FMP_SOURCE,
                    source_url=f"{url}?from={start_date.isoformat()}&to={end_date.isoformat()}",
                    final_url=f"{url}?from={start_date.isoformat()}&to={end_date.isoformat()}",
                    published_at=report_date,
                    fetched_at=fetched_at,
                )
            )
        return items

    def fetch_quote(self, ticker: str) -> list[MarketSnapshot]:
        url = f"{FMP_BASE_URL}/quote/{ticker}"
        data = self.cache.get_json(FMP_SOURCE, url, params={"apikey": self.api_key})
        if not isinstance(data, list):
            return []

        fetched_at = utc_now_iso()
        items: list[MarketSnapshot] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            items.append(
                MarketSnapshot(
                    ticker=ticker,
                    name=truncate(row.get("name"), 160),
                    market="US",
                    price=_float_or_none(row.get("price")),
                    currency=None,
                    change_percent=_float_or_none(row.get("changesPercentage")),
                    previous_close=_float_or_none(row.get("previousClose")),
                    open=_float_or_none(row.get("open")),
                    day_high=_float_or_none(row.get("dayHigh")),
                    day_low=_float_or_none(row.get("dayLow")),
                    volume=_float_or_none(row.get("volume")),
                    avg_volume=_float_or_none(row.get("avgVolume")),
                    market_cap=_float_or_none(row.get("marketCap")),
                    week_52_high=_float_or_none(row.get("yearHigh")),
                    week_52_low=_float_or_none(row.get("yearLow")),
                    data_timestamp=coerce_datetime_string(row.get("timestamp")),
                    observed_at=coerce_datetime_string(row.get("timestamp")),
                    raw=_public_raw(row),
                    source_name=FMP_SOURCE,
                    source_url=url,
                    published_at=coerce_datetime_string(row.get("timestamp")),
                    fetched_at=fetched_at,
                )
            )
        return items


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _public_raw(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key.lower() not in {"apikey", "token"}}
