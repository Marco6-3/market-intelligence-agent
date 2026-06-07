from pathlib import Path

import pandas as pd

from market_agent.models import NewsItem, ReportData, SourceRecord, StockItem
from market_agent.renderers.csv_sources import write_sources_csv
from market_agent.renderers.markdown import render_markdown


def _sample_report() -> ReportData:
    stock = StockItem(ticker="MU", name="Micron", market="US")
    news = NewsItem(
        ticker="MU",
        title="Micron expands memory roadmap",
        summary="HBM and DRAM update.",
        publisher="Example",
        symbols=["MU"],
        source_name="Example Source",
        source_url="https://example.com/mu",
        published_at="2026-06-01",
        fetched_at="2026-06-01T00:00:00Z",
    )
    return ReportData(
        run_date="2026-06-01",
        timezone="Asia/Singapore",
        watchlist=[stock],
        news=[news],
        sources=[
            SourceRecord(
                record_type="news",
                ticker="MU",
                title=news.title,
                source_name=news.source_name,
                source_url=news.source_url,
                published_at=news.published_at,
                fetched_at=news.fetched_at,
            )
        ],
    )


def test_markdown_includes_news_source_fields_and_not_available() -> None:
    markdown = render_markdown(_sample_report())

    assert "## Executive Summary" in markdown
    assert "## Critical Alerts" in markdown
    assert "## What Changed Since Last Report" in markdown
    assert "## Watchlist Snapshot Table" in markdown
    assert "## High Materiality Items" in markdown
    assert "## Analyst Review Queue" in markdown
    assert "## Per-Ticker Detail" in markdown
    assert "## Theme Tracker" in markdown
    assert "## Missing Data / Weak Claims" in markdown
    assert "source: Example Source" in markdown
    assert "published_at: 2026-06-01" in markdown
    assert "url: https://example.com/mu" in markdown
    assert "not available" in markdown
    assert "Questions for ChatGPT Analysis" in markdown


def test_sources_csv_has_required_columns(tmp_path: Path) -> None:
    path = tmp_path / "sources.csv"
    write_sources_csv(_sample_report(), path)

    frame = pd.read_csv(path)
    assert list(frame.columns) == [
        "record_type",
        "ticker",
        "title",
        "source_name",
        "source_url",
        "final_url",
        "aggregator_url",
        "source_quality",
        "freshness",
        "cluster_id",
        "published_at",
        "fetched_at",
    ]
    assert frame.loc[0, "source_url"] == "https://example.com/mu"
