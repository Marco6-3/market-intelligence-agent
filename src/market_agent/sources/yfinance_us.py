from __future__ import annotations

from typing import Any

import pandas as pd

from ..models import MarketSnapshot, StockItem
from ..utils.time import utc_now_iso

YFINANCE_SOURCE = "Yahoo Finance via yfinance"


class YFinanceClient:
    def fetch_quote(self, stock: StockItem) -> list[MarketSnapshot]:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError("yfinance is not installed. Install it with: pip install yfinance") from exc

        ticker = yf.Ticker(stock.ticker)
        history = ticker.history(period="5d", interval="1d", auto_adjust=False)
        if history.empty or "Close" not in history.columns:
            return []

        fast_info = _safe_fast_info(ticker)
        return snapshot_from_history(stock, history, fast_info)


def snapshot_from_history(
    stock: StockItem, history: pd.DataFrame, fast_info: dict[str, Any] | None = None
) -> list[MarketSnapshot]:
    valid = history.dropna(subset=["Close"])
    if valid.empty:
        return []

    last = valid.iloc[-1]
    previous = valid.iloc[-2] if len(valid) > 1 else None
    price = _float_or_none(last.get("Close"))
    previous_price = _float_or_none(previous.get("Close")) if previous is not None else None
    change_percent = None
    if price is not None and previous_price not in (None, 0):
        change_percent = ((price - previous_price) / previous_price) * 100

    observed_at = _index_to_iso(valid.index[-1])
    fetched_at = utc_now_iso()
    source_url = f"https://finance.yahoo.com/quote/{stock.ticker}"
    fast_info = fast_info or {}
    open_price = _first_float(
        fast_info, "open", "regularMarketOpen", "regular_market_open"
    ) or _float_or_none(last.get("Open"))
    day_high = _first_float(
        fast_info, "dayHigh", "day_high", "regularMarketDayHigh", "regular_market_day_high"
    ) or _float_or_none(last.get("High"))
    day_low = _first_float(
        fast_info, "dayLow", "day_low", "regularMarketDayLow", "regular_market_day_low"
    ) or _float_or_none(last.get("Low"))
    volume = _first_float(
        fast_info,
        "lastVolume",
        "last_volume",
        "volume",
        "regularMarketVolume",
        "regular_market_volume",
    )
    if volume is None:
        volume = _float_or_none(last.get("Volume"))

    return [
        MarketSnapshot(
            ticker=stock.ticker,
            name=stock.name,
            market="US",
            price=price,
            currency=_string_or_none(fast_info.get("currency")),
            change_percent=change_percent,
            previous_close=_first_float(
                fast_info,
                "previousClose",
                "previous_close",
                "regularMarketPreviousClose",
                "regular_market_previous_close",
            )
            or previous_price,
            open=open_price,
            day_high=day_high,
            day_low=day_low,
            volume=volume,
            avg_volume=_first_float(
                fast_info,
                "tenDayAverageVolume",
                "ten_day_average_volume",
                "threeMonthAverageVolume",
                "three_month_average_volume",
                "averageVolume",
                "average_volume",
            ),
            market_cap=_first_float(fast_info, "marketCap", "market_cap"),
            week_52_high=_first_float(
                fast_info, "yearHigh", "year_high", "fiftyTwoWeekHigh", "fifty_two_week_high"
            ),
            week_52_low=_first_float(
                fast_info, "yearLow", "year_low", "fiftyTwoWeekLow", "fifty_two_week_low"
            ),
            data_timestamp=observed_at,
            observed_at=observed_at,
            raw={
                "open": open_price,
                "high": day_high,
                "low": day_low,
                "close": price,
                "previous_close": previous_price,
                "volume": volume,
            },
            source_name=YFINANCE_SOURCE,
            source_url=source_url,
            published_at=observed_at,
            fetched_at=fetched_at,
        )
    ]


def _safe_fast_info(ticker: Any) -> dict[str, Any]:
    try:
        info = ticker.fast_info
        return dict(info) if info else {}
    except Exception:
        return {}


def _index_to_iso(value: Any) -> str:
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value)


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _first_float(container: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _float_or_none(container.get(key))
        if value is not None:
            return value
    return None
