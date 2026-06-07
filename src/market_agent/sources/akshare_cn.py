from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from ..models import MarketSnapshot, NewsItem, StockItem
from ..utils.text import clean_text, truncate
from ..utils.time import coerce_datetime_string
from ..utils.time import utc_now_iso

AKSHARE_SOURCE = "AKShare"
AKSHARE_ANNOUNCEMENT_SOURCE = "AKShare CN announcements"


class AkshareCNClient:
    def fetch_snapshot(self, stock: StockItem) -> list[MarketSnapshot]:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("AKShare is not installed. Install it with: pip install akshare") from exc

        frame = ak.stock_zh_a_spot_em()
        code = normalize_cn_stock_code(stock.ticker)
        rows = frame[frame["代码"].astype(str) == code]
        if rows.empty:
            return []

        row = rows.iloc[0].to_dict()
        fetched_at = utc_now_iso()
        return [
            MarketSnapshot(
                ticker=stock.ticker,
                name=str(row.get("名称") or stock.name),
                market="CN",
                price=_float_or_none(row.get("最新价")),
                currency="CNY",
                change_percent=_float_or_none(row.get("涨跌幅")),
                previous_close=_float_or_none(row.get("昨收")),
                open=_float_or_none(row.get("今开")),
                day_high=_float_or_none(row.get("最高")),
                day_low=_float_or_none(row.get("最低")),
                volume=_float_or_none(row.get("成交量")),
                avg_volume=None,
                market_cap=_float_or_none(row.get("总市值")),
                week_52_high=None,
                week_52_low=None,
                data_timestamp=fetched_at,
                observed_at=fetched_at,
                raw={str(key): value for key, value in row.items()},
                source_name=AKSHARE_SOURCE,
                source_url="https://quote.eastmoney.com/",
                published_at=fetched_at,
                fetched_at=fetched_at,
            )
        ]

    def fetch_announcements(self, stock: StockItem, limit: int = 5) -> list[NewsItem]:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("AKShare is not installed. Install it with: pip install akshare") from exc

        code = normalize_cn_stock_code(stock.ticker)
        frames = _collect_notice_frames(ak)
        fetched_at = utc_now_iso()
        items: list[NewsItem] = []
        for frame in frames:
            if frame.empty:
                continue
            for row in frame.to_dict(orient="records"):
                if not _row_matches_stock(row, stock, code):
                    continue
                title = truncate(_first_present(row, ["公告标题", "标题", "公告名称", "title"]), 280)
                if not title:
                    continue
                published_at = coerce_datetime_string(
                    _first_present(row, ["公告时间", "公告日期", "日期", "time", "date"])
                )
                items.append(
                    NewsItem(
                        ticker=stock.ticker,
                        item_type="cn_announcement",
                        title=title,
                        summary=f"title_summary: {title}",
                        summary_confidence="low",
                        why_it_matters=(
                            "A-share company announcement or financial-report title from AKShare; "
                            "read the source document before using it as a thesis claim."
                        ),
                        materiality=_classify_cn_announcement_title(title),
                        thesis_effect="needs_manual_review",
                        confidence="medium",
                        publisher=stock.name,
                        symbols=[stock.ticker, code],
                        source_name=AKSHARE_ANNOUNCEMENT_SOURCE,
                        source_url=_first_url(row) or "not available",
                        final_url=_first_url(row) or "not available",
                        published_at=published_at,
                        fetched_at=fetched_at,
                    )
                )
                if len(items) >= limit:
                    return items
        return items


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_cn_stock_code(ticker: str) -> str:
    return ticker.strip().upper().replace(".SH", "").replace(".SZ", "").replace(".BJ", "")


def _collect_notice_frames(ak: Any) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    notice_func = getattr(ak, "stock_notice_report", None)
    if notice_func is None:
        return frames

    call_specs: list[dict[str, Any]] = [{"symbol": "全部"}]
    today = datetime.utcnow().date()
    for offset in range(0, 14):
        call_specs.append({"symbol": "全部", "date": (today - timedelta(days=offset)).strftime("%Y%m%d")})

    for kwargs in call_specs:
        try:
            frame = notice_func(**kwargs)
        except TypeError:
            continue
        except Exception:
            continue
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            frames.append(frame)
            if len(frames) >= 3:
                break
    return frames


def _row_matches_stock(row: dict[str, Any], stock: StockItem, code: str) -> bool:
    haystack = " ".join(clean_text(value) or "" for value in row.values())
    candidates = [code, stock.ticker, stock.name, *stock.aliases]
    return any(candidate and str(candidate) in haystack for candidate in candidates)


def _first_present(row: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        value = row.get(key)
        if clean_text(value):
            return str(value)
    return None


def _first_url(row: dict[str, Any]) -> str | None:
    for value in row.values():
        text = clean_text(value)
        if text and text.startswith(("http://", "https://")):
            return text
    return None


def _classify_cn_announcement_title(title: str) -> str:
    lowered = title.casefold()
    if any(term in lowered for term in ["年报", "季报", "业绩", "利润", "重组", "定增", "重大"]):
        return "medium"
    return "low"
