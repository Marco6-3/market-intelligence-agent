import json
from pathlib import Path

import pandas as pd

from market_agent.models import (
    AnalystTriage,
    AnalystTriageItem,
    FreshnessInfo,
    IntelligenceItem,
    ReportData,
    SourceRecord,
    StockItem,
    SummaryFields,
)
from market_agent.renderers.csv_sources import write_sources_csv
from market_agent.renderers.json_export import write_json_report
from market_agent.renderers.markdown import render_markdown


def _sample_item() -> IntelligenceItem:
    freshness = FreshnessInfo(
        published_days_ago=1,
        is_newly_published=True,
        is_newly_discovered=False,
        freshness_label="fresh",
    )
    return IntelligenceItem(
        ticker="MU",
        company_name="Micron",
        category="Memory and Storage",
        item_type="public_news",
        title="Micron HBM4 demand update",
        summary=SummaryFields(
            what_happened="Article excerpt says Micron HBM4 demand improved.",
            affected_company="Micron",
            related_theme="HBM4",
            possible_financial_impact="May affect revenue and supply assumptions.",
            evidence_strength="medium",
            follow_up_needed="Verify with official company source.",
        ),
        why_it_matters="Tracked theme matched and source is recent.",
        materiality="medium",
        materiality_score=72,
        score_breakdown={"source_score": 20},
        thesis_effect="supports_thesis",
        confidence="medium",
        content_depth="article_excerpt",
        freshness=freshness,
        related_themes=["HBM4"],
        matched_terms=["HBM4"],
        source_name="Reuters",
        source_url="https://example.com/mu",
        canonical_url="https://example.com/mu",
        canonical_url_status="resolved",
        published_at="2026-06-01",
        fetched_at="2026-06-01T00:00:00Z",
    )


def _sample_report() -> ReportData:
    stock = StockItem(ticker="MU", name="Micron", market="US", category="Memory and Storage")
    item = _sample_item()
    triage_item = AnalystTriageItem(
        ticker=item.ticker,
        title=item.title,
        reason="Medium materiality item needs review.",
        follow_up_needed=item.summary.follow_up_needed,
        materiality=item.materiality,
        materiality_score=item.materiality_score,
        freshness_label="fresh",
        evidence_strength="medium",
        source_url=item.source_url,
    )
    return ReportData(
        run_date="2026-06-01",
        timezone="Asia/Singapore",
        scope="daily",
        watchlist=[stock],
        items=[item],
        analyst_triage=AnalystTriage(watch_items=[triage_item]),
        missing_data=["MU: SEC filings not available"],
        sources=[
            SourceRecord(
                record_type="intelligence_item",
                ticker="MU",
                title=item.title,
                source_name=item.source_name,
                source_url=item.source_url,
                canonical_url=item.canonical_url,
                canonical_url_status="resolved",
                source_quality=item.source_quality,
                freshness=item.freshness,
                content_depth=item.content_depth,
                published_at=item.published_at,
                fetched_at=item.fetched_at,
            )
        ],
    )


def test_markdown_contains_required_sections() -> None:
    markdown = render_markdown(_sample_report())

    for heading in [
        "## Executive Summary",
        "## Critical Alerts",
        "## Analyst Triage",
        "## What Changed Since Last Report",
        "## Price Action Review",
        "## Category Summary",
        "## Watchlist Snapshot Table",
        "## High Materiality Items",
        "## Per-Ticker Detail",
        "## Theme Tracker",
        "## Missing Data / Weak Claims",
        "## Questions for ChatGPT Analysis",
        "## Source Notes",
    ]:
        assert heading in markdown
    assert "content_depth: article_excerpt" in markdown
    assert "published_at: 2026-06-01" in markdown
    assert "AKShare" not in markdown
    assert "Tushare" not in markdown


def test_json_items_include_required_fields(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    write_json_report(_sample_report(), path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    item = payload["items"][0]
    for field in [
        "ticker",
        "company_name",
        "category",
        "item_type",
        "title",
        "summary",
        "why_it_matters",
        "materiality",
        "materiality_score",
        "score_breakdown",
        "thesis_effect",
        "confidence",
        "content_depth",
        "freshness",
        "related_themes",
        "matched_terms",
        "source_name",
        "source_url",
        "published_at",
        "fetched_at",
    ]:
        assert field in item


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
        "canonical_url",
        "canonical_url_status",
        "aggregator_source",
        "aggregator_url",
        "source_quality",
        "freshness",
        "cluster_id",
        "content_depth",
        "published_at",
        "fetched_at",
    ]
    assert frame.loc[0, "source_url"] == "https://example.com/mu"
