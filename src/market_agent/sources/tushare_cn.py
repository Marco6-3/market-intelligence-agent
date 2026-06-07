from __future__ import annotations

from datetime import date, timedelta

from ..models import MarketSnapshot, StockItem
from ..utils.time import utc_now_iso

TUSHARE_SOURCE = "Tushare"


class TushareCNClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def fetch_recent_daily(self, stock: StockItem, run_date: date) -> list[MarketSnapshot]:
        try:
            import tushare as ts
        except ImportError as exc:
            raise RuntimeError("Tushare is not installed. Install it with: pip install tushare") from exc

        pro = ts.pro_api(self.token)
        end_date = run_date.strftime("%Y%m%d")
        start_date = (run_date - timedelta(days=10)).strftime("%Y%m%d")
        frame = pro.daily(ts_code=stock.ticker, start_date=start_date, end_date=end_date)
        if frame.empty:
            return []

        row = frame.iloc[0].to_dict()
        fetched_at = utc_now_iso()
        trade_date = str(row.get("trade_date") or "")
        published_at = (
            f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}" if len(trade_date) == 8 else fetched_at
        )
        return [
            MarketSnapshot(
                ticker=stock.ticker,
                name=stock.name,
                market="CN",
                price=_float_or_none(row.get("close")),
                currency="CNY",
                change_percent=_float_or_none(row.get("pct_chg")),
                observed_at=published_at,
                raw={str(key): value for key, value in row.items()},
                source_name=TUSHARE_SOURCE,
                source_url="https://tushare.pro/",
                published_at=published_at,
                fetched_at=fetched_at,
            )
        ]


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
