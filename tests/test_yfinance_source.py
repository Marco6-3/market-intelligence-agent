import pandas as pd

from market_agent.models import StockItem
from market_agent.sources.yfinance_us import snapshot_from_history


def test_snapshot_from_history_builds_source_fields() -> None:
    stock = StockItem(ticker="MU", name="Micron", market="US")
    history = pd.DataFrame(
        {
            "Open": [98.0, 100.0],
            "High": [101.0, 104.0],
            "Low": [97.0, 99.0],
            "Close": [100.0, 102.3456],
            "Volume": [1000, 1200],
        },
        index=pd.to_datetime(["2026-05-29", "2026-06-01"]),
    )

    result = snapshot_from_history(
        stock,
        history,
        {
            "currency": "USD",
            "previousClose": 100.111,
            "tenDayAverageVolume": 1500,
            "marketCap": 1234567890,
            "yearHigh": 130.555,
            "yearLow": 80.444,
        },
    )

    assert len(result) == 1
    snapshot = result[0]
    assert snapshot.source_name == "Yahoo Finance via yfinance"
    assert snapshot.source_url == "https://finance.yahoo.com/quote/MU"
    assert snapshot.published_at == "2026-06-01"
    assert snapshot.fetched_at
    assert snapshot.price == 102.35
    assert snapshot.change_percent == 2.35
    assert snapshot.previous_close == 100.11
    assert snapshot.open == 100.0
    assert snapshot.day_high == 104.0
    assert snapshot.day_low == 99.0
    assert snapshot.volume == 1200
    assert snapshot.avg_volume == 1500
    assert snapshot.market_cap == 1234567890
    assert snapshot.week_52_high == 130.56
    assert snapshot.week_52_low == 80.44
    assert snapshot.data_timestamp == "2026-06-01"
