from __future__ import annotations

from collections import defaultdict

from ..freshness import freshness_label
from ..intelligence import (
    earnings_calendar_to_item,
    filing_to_item,
    market_snapshot_to_item,
    news_to_item,
)
from ..models import IntelligenceItem, MarketSnapshot, ReportData, SummaryFields
from ..scoring import high_allowed_in_critical


def render_markdown(report: ReportData) -> str:
    lines: list[str] = []
    items = _items_for_report(report)
    lines.append(f"# Daily Market Intelligence Brief - {report.run_date}")
    lines.append("")
    _render_executive_summary(lines, report, items)
    _render_critical_alerts(lines, report, items)
    _render_analyst_triage(lines, report)
    _render_changes(lines, report)
    _render_price_action_review(lines, report)
    _render_category_summary(lines, report)
    _render_snapshot_table(lines, report)
    _render_high_materiality(lines, items)
    _render_per_ticker_detail(lines, report, items)
    _render_theme_tracker(lines, report, items)
    _render_missing_data(lines, report, items)
    _render_questions(lines, report)
    _render_source_notes(lines)
    return "\n".join(lines)


def _render_executive_summary(
    lines: list[str], report: ReportData, items: list[IntelligenceItem]
) -> None:
    high_count = sum(1 for item in items if item.materiality == "high")
    medium_count = sum(1 for item in items if item.materiality == "medium")
    low_count = sum(1 for item in items if item.materiality == "low")
    fresh_count = sum(1 for item in items if freshness_label(item.freshness) == "fresh")
    recent_count = sum(1 for item in items if freshness_label(item.freshness) == "recent")
    stale_count = sum(1 for item in items if freshness_label(item.freshness) == "stale_context")
    top_items = _rank_items(items)[:3]

    lines.append("## Executive Summary")
    lines.append(f"- Watchlist count: {len(report.watchlist)}")
    lines.append(f"- Market snapshots count: {len(report.market_snapshot)}")
    lines.append(f"- News count: {len(report.news)}")
    lines.append(f"- Filings count: {len(report.filings)}")
    lines.append(f"- Theme mentions count: {len(report.theme_mentions)}")
    lines.append(f"- High / medium / low count: {high_count} / {medium_count} / {low_count}")
    lines.append(f"- Fresh / recent / stale count: {fresh_count} / {recent_count} / {stale_count}")
    lines.append("- Top 3 things to review:")
    if top_items:
        for item in top_items:
            lines.append(f"  - [{item.materiality} {item.materiality_score}] {item.ticker}: {item.title}")
    else:
        lines.append("  - not available")
    lines.append("- Missing data summary:")
    if report.missing_data:
        for entry in report.missing_data[:8]:
            lines.append(f"  - {entry}")
    else:
        lines.append("  - not available")
    lines.append("")


def _render_critical_alerts(
    lines: list[str], report: ReportData, items: list[IntelligenceItem]
) -> None:
    lines.append("## Critical Alerts")
    critical = [
        item
        for item in items
        if item.materiality == "high"
        and high_allowed_in_critical(item)
        and freshness_label(item.freshness) in {"fresh", "recent"}
    ][:10]
    if critical:
        for item in critical:
            _render_item(lines, item)
    else:
        lines.append("not available")
    if report.alerts:
        lines.append("### Pipeline Warnings")
        for alert in report.alerts:
            lines.append(f"- [{alert.severity}] {alert.message} (source: {alert.source_name}, fetched_at: {alert.fetched_at})")
    lines.append("")


def _render_analyst_triage(lines: list[str], report: ReportData) -> None:
    lines.append("## Analyst Triage")
    sections = [
        ("### Must Review Today", report.analyst_triage.must_review_today),
        ("### Watch Items", report.analyst_triage.watch_items),
        ("### Background Context", report.analyst_triage.background_context),
        ("### Noise / Duplicate / Low Confidence", report.analyst_triage.noise_duplicate_low_confidence),
    ]
    for heading, rows in sections:
        lines.append(heading)
        if rows:
            for row in rows:
                lines.append(f"- [{row.materiality} {row.materiality_score}] {row.ticker}: {row.title}")
                lines.append(f"  - reason: {row.reason}")
                lines.append(f"  - follow_up_needed: {row.follow_up_needed}")
                lines.append(f"  - evidence_strength: {row.evidence_strength}; freshness: {row.freshness_label}; url: {row.source_url}")
        else:
            lines.append("not available")
    lines.append("")


def _render_changes(lines: list[str], report: ReportData) -> None:
    changes = report.changes_since_last_report
    lines.append("## What Changed Since Last Report")
    lines.append(f"- Compared with previous report: {changes.status}")
    if changes.previous_report_path:
        lines.append(f"- previous_report: {changes.previous_report_path}")
    lines.append("- Price changes:")
    if changes.price_changes:
        for item in changes.price_changes:
            lines.append(f"  - {item.ticker}: {_number(item.previous_price)} -> {_number(item.current_price)} ({_signed_number(item.change_percent)}%)")
    else:
        lines.append("  - not available")
    lines.append("- New official filings:")
    _render_item_titles(lines, changes.new_filings)
    lines.append("- New fresh news:")
    _render_item_titles(lines, changes.newly_published)
    lines.append("- Newly discovered stale items:")
    _render_item_titles(lines, changes.newly_discovered_stale)
    lines.append("- New theme mentions:")
    if changes.new_theme_mentions:
        for mention in changes.new_theme_mentions[:20]:
            lines.append(f"  - {mention}")
    else:
        lines.append("  - not available")
    lines.append("- Removed / no longer active alerts:")
    if changes.removed_or_no_longer_active_alerts:
        for title in changes.removed_or_no_longer_active_alerts:
            lines.append(f"  - {title}")
    else:
        lines.append("  - not available")
    lines.append("")


def _render_price_action_review(lines: list[str], report: ReportData) -> None:
    lines.append("## Price Action Review")
    snapshots = list(_latest_snapshot_by_ticker(report.market_snapshot).values())
    movers = [
        item
        for item in snapshots
        if item.change_percent is not None and abs(item.change_percent) >= 2.5
    ]
    focus_tickers = {"WDC", "LRCX", "KLAC", "STX"}
    focus = [
        item
        for item in snapshots
        if item.ticker.upper() in focus_tickers
        and item.change_percent is not None
        and abs(item.change_percent) >= 1.5
        and item not in movers
    ]
    review_items = sorted([*movers, *focus], key=lambda item: abs(item.change_percent or 0), reverse=True)
    if not review_items:
        lines.append("not available")
        lines.append("")
        return
    for item in review_items[:12]:
        volume_note = _volume_note(item)
        direction = "up" if (item.change_percent or 0) > 0 else "down"
        lines.append(
            f"- {item.ticker}: {direction} {_signed_number(item.change_percent)}% to {_number(item.price)} "
            f"({volume_note}). Follow-up: connect the move to filings, earnings, news clusters, or sector read-throughs before treating it as thesis signal."
        )
    lines.append("")


def _render_category_summary(lines: list[str], report: ReportData) -> None:
    lines.append("## Category Summary")
    desired = [
        "AI Compute",
        "AI ASIC and Networking",
        "Semiconductor Equipment",
        "Memory and Storage",
        "AI Cloud Demand",
        "Robotics / Physical AI",
    ]
    summaries = {summary.category: summary for summary in report.category_summary}
    for category in desired:
        matched = _category_lookup(summaries, category)
        lines.append(f"### {category}")
        if matched:
            lines.append(f"- Current read: {_category_current_read(category, matched)}")
            lines.append(f"- Evidence to verify: {_category_evidence_line(matched)}")
            lines.append(f"- Risk / contradiction: {_value(matched.risk_signal)}")
            lines.append(f"- Evidence strength: {matched.evidence_strength}")
        else:
            lines.append("- Current read: not available")
            lines.append("- Evidence to verify: not available")
            lines.append("- Risk / contradiction: not available")
    lines.append("")


def _render_snapshot_table(lines: list[str], report: ReportData) -> None:
    lines.append("## Watchlist Snapshot Table")
    lines.append(
        "| Ticker | Name | Category | Currency | Price | Change % | Previous Close | Open | Day High | "
        "Day Low | Volume | Avg Volume | Market Cap | 52W High | 52W Low | Data Timestamp | Source |"
    )
    lines.append(
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"
    )
    snapshots = _latest_snapshot_by_ticker(report.market_snapshot)
    for stock in report.watchlist:
        item = snapshots.get(stock.ticker)
        if not item:
            lines.append(
                f"| {_escape(stock.ticker)} | {_escape(stock.name)} | {_escape(stock.category)} | not available | not available | "
                "not available | not available | not available | not available | not available | "
                "not available | not available | not available | not available | not available | not available | not available |"
            )
            continue
        lines.append(
            f"| {_escape(item.ticker)} | {_escape(item.name or stock.name)} | {_escape(stock.category)} | "
            f"{_escape(item.currency or 'not available')} | {_number(item.price)} | "
            f"{_number(item.change_percent)} | {_number(item.previous_close)} | "
            f"{_number(item.open)} | {_number(item.day_high)} | {_number(item.day_low)} | "
            f"{_integer(item.volume)} | {_integer(item.avg_volume)} | {_integer(item.market_cap)} | "
            f"{_number(item.week_52_high)} | {_number(item.week_52_low)} | "
            f"{_escape(item.data_timestamp or item.observed_at or 'not available')} | "
            f"{_escape(item.source_name)} |"
        )
    lines.append("")


def _render_high_materiality(lines: list[str], items: list[IntelligenceItem]) -> None:
    lines.append("## High Materiality Items")
    high = [item for item in _rank_items(items) if item.materiality == "high" and high_allowed_in_critical(item)]
    if high:
        for item in high:
            _render_item(lines, item)
    else:
        lines.append("not available")
    lines.append("")


def _render_per_ticker_detail(
    lines: list[str], report: ReportData, items: list[IntelligenceItem]
) -> None:
    lines.append("## Per-Ticker Detail")
    for stock in report.watchlist:
        lines.append(f"### {stock.ticker} - {stock.name}")
        ticker_items = [item for item in _rank_items(items) if item.ticker == stock.ticker]
        lines.append("#### Top Items")
        if ticker_items:
            for item in ticker_items[:5]:
                _render_item(lines, item)
        else:
            lines.append("not available")
        lines.append("#### Market Snapshot")
        snapshot = next((item for item in ticker_items if item.item_type == "market_snapshot"), None)
        lines.append(snapshot.summary.what_happened if snapshot else "not available")
        lines.append("#### Filings Summary")
        _render_item_titles(lines, [item for item in ticker_items if item.item_type == "sec_filing"][:5])
        lines.append("#### News Summary")
        _render_item_titles(lines, [item for item in ticker_items if item.item_type in {"public_news", "ir_news"}][:5])
        lines.append("#### Theme Mentions")
        themes = sorted({theme for item in ticker_items for theme in item.related_themes})
        lines.append(", ".join(themes) if themes else "not available")
        lines.append("#### Missing Data")
        missing = [entry for entry in report.missing_data if entry.startswith(f"{stock.ticker}:")]
        if missing:
            for entry in missing:
                lines.append(f"- {entry}")
        else:
            lines.append("not available")
        lines.append("")


def _render_theme_tracker(
    lines: list[str], report: ReportData, items: list[IntelligenceItem]
) -> None:
    lines.append("## Theme Tracker")
    grouped: dict[str, list[IntelligenceItem]] = defaultdict(list)
    for item in items:
        for theme in item.related_themes:
            grouped[theme].append(item)
    if grouped:
        for theme in sorted(grouped):
            theme_items = _rank_items(grouped[theme])
            tickers = sorted({item.ticker for item in theme_items})
            top_fresh = [item for item in theme_items if freshness_label(item.freshness) in {"fresh", "recent"}][:3]
            signal = _theme_signal(theme_items)
            evidence = _theme_evidence(theme_items)
            lines.append(f"### {theme}")
            lines.append(f"- mention count: {len(theme_items)}")
            lines.append(f"- related tickers: {', '.join(tickers) if tickers else 'not available'}")
            lines.append("- top fresh items:")
            _render_item_titles(lines, top_fresh)
            lines.append(f"- positive / negative / mixed signal: {signal}")
            lines.append(f"- evidence strength: {evidence}")
    else:
        lines.append("not available")
    lines.append("")


def _render_missing_data(
    lines: list[str], report: ReportData, items: list[IntelligenceItem]
) -> None:
    lines.append("## Missing Data / Weak Claims")
    entries = list(report.missing_data)
    for item in items:
        if item.materiality in {"high", "medium"} and item.content_depth == "headline_only":
            entries.append(f"{item.ticker}: {item.title} is headline_only")
        if item.materiality in {"high", "medium"} and item.summary.evidence_strength == "low":
            entries.append(f"{item.ticker}: {item.title} has weak evidence")
    if entries:
        for entry in _dedupe_strings(entries):
            lines.append(f"- {entry}")
    else:
        lines.append("not available")
    lines.append("")


def _render_questions(lines: list[str], report: ReportData) -> None:
    lines.append("## Questions for ChatGPT Analysis")
    if report.questions_for_analysis:
        for question in report.questions_for_analysis:
            lines.append(f"- {question}")
    else:
        lines.append("not available")
    lines.append("")


def _render_source_notes(lines: list[str]) -> None:
    lines.append("## Source Notes")
    lines.append("- All records include source_url/source_name/published_at/fetched_at in JSON and source CSV.")
    lines.append("- yfinance is a non-official market data source and is only used for personal research context.")
    lines.append("- Google News RSS is an aggregator fallback; canonical_url is preferred when it can be resolved.")
    lines.append("- This system collects, summarizes, classifies, and triages information; it does not provide buy/sell recommendations, target prices, or automated trading signals.")
    lines.append("")


def _render_item(lines: list[str], item: IntelligenceItem) -> None:
    summary = _summary(item.summary)
    lines.append(f"- **{item.ticker} - {item.title}**")
    lines.append(
        f"  - item_type: {item.item_type}; materiality: {item.materiality}; "
        f"score: {item.materiality_score}; thesis_effect: {item.thesis_effect}; confidence: {item.confidence}"
    )
    lines.append(
        f"  - freshness: {freshness_label(item.freshness)}; content_depth: {item.content_depth}; "
        f"evidence_strength: {summary.evidence_strength}; source_quality: {item.source_quality}"
    )
    lines.append(f"  - what_happened: {_value(summary.what_happened)}")
    lines.append(f"  - why_it_matters: {_value(item.why_it_matters)}")
    lines.append(f"  - possible_financial_impact: {_value(summary.possible_financial_impact)}")
    lines.append(f"  - follow_up_needed: {_value(summary.follow_up_needed)}")
    lines.append(f"  - related_themes: {', '.join(item.related_themes) if item.related_themes else 'not available'}")
    lines.append(f"  - matched_terms: {', '.join(item.matched_terms) if item.matched_terms else 'not available'}")
    lines.append(
        f"  - source: {item.source_name}; published_at: {_value(item.published_at)}; "
        f"fetched_at: {item.fetched_at}; url: {_display_url(item)}"
    )
    if item.aggregator_url:
        suffix = "aggregator link only" if not item.canonical_url else "aggregator preserved"
        lines.append(f"  - aggregator_url: {item.aggregator_url} ({suffix})")
    if item.cluster_sources:
        lines.append(f"  - news_cluster: {item.cluster_id}; source_count: {len(item.cluster_sources)}")


def _render_item_titles(lines: list[str], items: list[IntelligenceItem]) -> None:
    if items:
        for item in items[:10]:
            lines.append(f"  - [{item.materiality} {item.materiality_score}] {item.ticker}: {item.title}")
    else:
        lines.append("  - not available")


def _items_for_report(report: ReportData) -> list[IntelligenceItem]:
    if report.items:
        return report.items
    stocks_by_ticker = {stock.ticker: stock for stock in report.watchlist}
    items: list[IntelligenceItem] = []
    items.extend(market_snapshot_to_item(snapshot, stocks_by_ticker.get(snapshot.ticker)) for snapshot in report.market_snapshot)
    items.extend(news_to_item(item) for item in report.news)
    items.extend(filing_to_item(item) for item in report.filings)
    items.extend(earnings_calendar_to_item(item, stocks_by_ticker.get(item.ticker)) for item in report.earnings_calendar)
    return items


def _rank_items(items: list[IntelligenceItem]) -> list[IntelligenceItem]:
    return sorted(
        items,
        key=lambda item: (
            -item.materiality_score,
            {"high": 0, "medium": 1, "low": 2}.get(item.materiality, 9),
            item.ticker,
            item.title,
        ),
    )


def _latest_snapshot_by_ticker(items: list[MarketSnapshot]) -> dict[str, MarketSnapshot]:
    latest: dict[str, MarketSnapshot] = {}
    for item in items:
        latest[item.ticker] = item
    return latest


def _category_lookup(summaries: dict[str, object], category: str) -> object | None:
    if category in summaries:
        return summaries[category]
    if category == "AI ASIC and Networking":
        return summaries.get("AI ASIC and Networking") or summaries.get("AI Networking")
    if category == "Memory and Storage":
        for key in ("Memory", "Storage", "NAND and SSD", "Memory and Semiconductors"):
            if key in summaries:
                return summaries[key]
    if category == "Robotics / Physical AI":
        for key in ("Robotics", "Warehouse Robotics", "Robotics and Semiconductor Test", "Industrial Automation"):
            if key in summaries:
                return summaries[key]
    return None


def _category_current_read(category: str, summary: object) -> str:
    movers = getattr(summary, "key_movers", [])
    news = getattr(summary, "important_news", [])
    demand = _value(getattr(summary, "demand_signal", None))
    if movers and news:
        return (
            f"{category} has both price action and information-flow signals. "
            f"Price action: {_list_value(movers[:3])}. News/filing signal: {_list_value(news[:3])}. "
            f"Tracked demand/theme read: {demand}."
        )
    if movers:
        return (
            f"{category} is being driven mainly by price action today. "
            f"Key moves: {_list_value(movers[:3])}. Treat as triage until matched with filings or high-quality news."
        )
    if news:
        return (
            f"{category} has information-flow signal without a strong captured price move. "
            f"Top items: {_list_value(news[:3])}. Tracked demand/theme read: {demand}."
        )
    if demand != "not available":
        return f"{category} has theme mentions but no decisive high-quality catalyst yet. Tracked demand/theme read: {demand}."
    return "No decisive fresh category signal captured; keep this bucket in background monitoring."


def _category_evidence_line(summary: object) -> str:
    news = getattr(summary, "important_news", [])
    movers = getattr(summary, "key_movers", [])
    if news:
        return _list_value(news[:4])
    if movers:
        return _list_value(movers[:4])
    return "not available"


def _theme_signal(items: list[IntelligenceItem]) -> str:
    effects = {item.thesis_effect for item in items}
    if "supports_thesis" in effects and "weakens_thesis" in effects:
        return "mixed"
    if "supports_thesis" in effects:
        return "positive"
    if "weakens_thesis" in effects:
        return "negative"
    return "mixed" if effects else "not available"


def _theme_evidence(items: list[IntelligenceItem]) -> str:
    if any(item.summary.evidence_strength == "high" for item in items):
        return "high"
    if any(item.summary.evidence_strength == "medium" for item in items):
        return "medium"
    return "low"


def _summary(value: object) -> SummaryFields:
    if isinstance(value, SummaryFields):
        return value
    if isinstance(value, dict):
        return SummaryFields.model_validate(value)
    return SummaryFields.from_text(value)


def _display_url(item: IntelligenceItem) -> str:
    return item.canonical_url or item.final_url or item.source_url


def _list_value(values: list[str]) -> str:
    return "; ".join(values) if values else "not available"


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _value(value: object) -> str:
    if value is None or value == "":
        return "not available"
    return str(value)


def _number(value: float | None) -> str:
    return "not available" if value is None else f"{value:.2f}"


def _signed_number(value: float | None) -> str:
    return "not available" if value is None else f"{value:+.2f}"


def _integer(value: int | None) -> str:
    return "not available" if value is None else f"{value:,}"


def _volume_note(item: MarketSnapshot) -> str:
    if item.volume is None:
        return "volume not available"
    if item.avg_volume in (None, 0):
        return f"volume {_integer(item.volume)}"
    ratio = item.volume / item.avg_volume
    return f"volume {_integer(item.volume)}, {ratio:.1f}x average"


def _escape(value: object) -> str:
    return _value(value).replace("|", "\\|")
