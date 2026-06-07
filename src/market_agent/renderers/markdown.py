from __future__ import annotations

from ..intelligence import (
    earnings_calendar_to_item,
    filing_to_item,
    market_snapshot_to_item,
    news_to_item,
)
from ..models import IntelligenceItem, MarketSnapshot, ReportData


def render_markdown(report: ReportData) -> str:
    lines: list[str] = []
    items = _items_for_report(report)
    lines.append(f"# Daily Market Intelligence Brief - {report.run_date}")
    lines.append("")
    _render_executive_summary(lines, report, items)
    _render_critical_alerts(lines, report, items)
    _render_changes(lines, report)
    _render_snapshot_table(lines, report)
    _render_high_materiality(lines, items)
    _render_analyst_review_queue(lines, report)
    _render_per_ticker_detail(lines, report, items)
    _render_theme_tracker(lines, report)
    _render_missing_data(lines, report, items)
    _render_questions(lines, report)
    _render_source_notes(lines, report)
    return "\n".join(lines)


def _render_executive_summary(
    lines: list[str], report: ReportData, items: list[IntelligenceItem]
) -> None:
    high_count = sum(1 for item in items if item.materiality == "high")
    medium_count = sum(1 for item in items if item.materiality == "medium")
    low_count = sum(1 for item in items if item.materiality == "low")
    lines.append("## Executive Summary")
    lines.append(
        f"- Watchlist: {len(report.watchlist)} stocks; "
        f"market snapshots: {len(report.market_snapshot)}; news: {len(report.news)}; "
        f"filings: {len(report.filings)}; theme mentions: {len(report.theme_mentions)}."
    )
    lines.append(
        f"- Materiality mix: high={high_count}, medium={medium_count}, low={low_count}."
    )
    if items:
        top_items = [item for item in items if item.materiality in {"high", "medium"}][:3]
        if top_items:
            lines.append("- Top items to review:")
            for item in top_items:
                lines.append(
                    f"  - [{item.materiality}] {item.ticker} {item.title}: "
                    f"{_value(item.why_it_matters)}"
                )
    else:
        lines.append("- No source data was collected; check API keys, public RSS access, and network.")
    lines.append("")


def _render_critical_alerts(
    lines: list[str], report: ReportData, items: list[IntelligenceItem]
) -> None:
    lines.append("## Critical Alerts")
    critical = [item for item in items if item.materiality == "high"]
    if critical:
        for item in critical:
            lines.append(f"- [{item.ticker}] {item.title} ({item.item_type})")
            lines.append(f"  - why_it_matters: {_value(item.why_it_matters)}")
            lines.append(f"  - source: {item.source_name}; url: {_display_url(item)}")
    if report.alerts:
        for alert in report.alerts:
            lines.append(
                f"- [{alert.severity}] {alert.message} "
                f"(source: {alert.source_name}, fetched_at: {alert.fetched_at})"
            )
    if not critical and not report.alerts:
        lines.append("not available")
    lines.append("")


def _render_changes(lines: list[str], report: ReportData) -> None:
    changes = report.changes_since_last_report
    lines.append("## What Changed Since Last Report")
    lines.append(f"- {changes.status}")
    if changes.previous_report_path:
        lines.append(f"- previous_report: {changes.previous_report_path}")
    if changes.price_changes:
        lines.append("- Price changes:")
        for item in changes.price_changes:
            lines.append(
                f"  - {item.ticker}: {_number(item.previous_price)} -> "
                f"{_number(item.current_price)} ({_signed_number(item.change_percent)}%)"
            )
    if changes.new_filings:
        lines.append("- New filings:")
        for item in changes.new_filings[:10]:
            lines.append(f"  - [{item.materiality}] {item.ticker}: {item.title}")
    if changes.new_news:
        lines.append("- New news:")
        for item in changes.new_news[:10]:
            lines.append(f"  - [{item.materiality}] {item.ticker}: {item.title}")
    if changes.new_theme_mentions:
        lines.append("- New theme mentions:")
        for mention in changes.new_theme_mentions[:20]:
            lines.append(f"  - {mention}")
    if (
        changes.previous_report_path
        and not changes.price_changes
        and not changes.new_filings
        and not changes.new_news
        and not changes.new_theme_mentions
    ):
        lines.append("- No tracked changes detected.")
    lines.append("")


def _render_snapshot_table(lines: list[str], report: ReportData) -> None:
    lines.append("## Watchlist Snapshot Table")
    lines.append(
        "| Ticker | Name | Currency | Price | Change % | Previous Close | Open | Day High | "
        "Day Low | Volume | Avg Volume | Market Cap | 52W High | 52W Low | Data Timestamp | Source |"
    )
    lines.append(
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"
    )
    snapshots = _latest_snapshot_by_ticker(report.market_snapshot)
    for stock in report.watchlist:
        item = snapshots.get(stock.ticker)
        if not item:
            lines.append(
                f"| {_escape(stock.ticker)} | {_escape(stock.name)} | not available | not available | "
                "not available | not available | not available | not available | not available | "
                "not available | not available | not available | not available | not available | "
                "not available | not available |"
            )
            continue
        lines.append(
            f"| {_escape(item.ticker)} | {_escape(item.name or stock.name)} | "
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
    high = [item for item in items if item.materiality == "high"]
    medium = [item for item in items if item.materiality == "medium"]
    if high:
        lines.append("### High")
        for item in high:
            _render_item(lines, item)
    else:
        lines.append("### High")
        lines.append("not available")
    lines.append("")
    if medium:
        lines.append("### Medium")
        for item in medium:
            _render_item(lines, item)
    else:
        lines.append("### Medium")
        lines.append("not available")
    lines.append("")


def _render_analyst_review_queue(lines: list[str], report: ReportData) -> None:
    lines.append("## Analyst Review Queue")
    if report.analyst_review_queue:
        for item in report.analyst_review_queue[:5]:
            lines.append(f"- **{item.ticker} - {item.core_claim}**")
            lines.append(f"  - why_it_matters: {_value(item.why_it_matters)}")
            lines.append(f"  - evidence_strength: {_value(item.evidence_strength)}")
            lines.append(f"  - possible_thesis_effect: {item.possible_thesis_effect}")
            if item.follow_up_questions:
                lines.append("  - follow_up_questions:")
                for question in item.follow_up_questions:
                    lines.append(f"    - {question}")
            lines.append(
                f"  - item_type: {item.item_type}; materiality: {item.materiality}; "
                f"source_quality: {item.source_quality}; freshness: {item.freshness}; "
                f"url: {item.source_url}"
            )
    else:
        lines.append("not available")
    lines.append("")


def _render_per_ticker_detail(
    lines: list[str], report: ReportData, items: list[IntelligenceItem]
) -> None:
    lines.append("## Per-Ticker Detail")
    for stock in report.watchlist:
        lines.append(f"### {stock.ticker} - {stock.name}")
        ticker_items = [item for item in items if item.ticker == stock.ticker]
        prioritized = [item for item in ticker_items if item.materiality in {"high", "medium"}]
        if prioritized:
            for item in prioritized:
                _render_item(lines, item)
        else:
            lines.append("not available")

        low_items = [item for item in ticker_items if item.materiality == "low"]
        lines.append("#### Low Materiality Appendix")
        if low_items:
            for item in low_items:
                _render_item(lines, item)
        else:
            lines.append("not available")
        lines.append("")


def _render_theme_tracker(lines: list[str], report: ReportData) -> None:
    lines.append("## Theme Tracker")
    if report.theme_mentions:
        for item in report.theme_mentions:
            lines.append(
                f"- {item.ticker} / {item.theme}: {item.title}; "
                f"source: {item.source_name}; published_at: {_value(item.published_at)}; "
                f"url: {item.source_url}"
            )
    else:
        lines.append("not available")
    lines.append("")


def _render_missing_data(
    lines: list[str], report: ReportData, items: list[IntelligenceItem]
) -> None:
    lines.append("## Missing Data / Weak Claims")
    weak: list[str] = []
    for stock in report.watchlist:
        if not any(item.ticker == stock.ticker for item in report.market_snapshot):
            weak.append(f"{stock.ticker}: market snapshot not available")
        if not any(item.ticker == stock.ticker for item in report.news):
            weak.append(f"{stock.ticker}: news / announcements not available")
        if stock.market == "US" and not any(item.ticker == stock.ticker for item in report.filings):
            weak.append(f"{stock.ticker}: SEC filings not available")
    for item in items:
        if (
            item.confidence == "low"
            or item.summary_confidence == "low"
            or item.source_quality in {"low", "unknown"}
            or item.source_url == "not available"
        ):
            weak.append(
                f"{item.ticker}: {item.title} has confidence={item.confidence}, "
                f"summary_confidence={item.summary_confidence}, "
                f"source_quality={item.source_quality}, source_url={item.source_url}"
            )
    for alert in report.alerts:
        weak.append(f"warning: {alert.message}")
    if weak:
        for entry in weak:
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


def _render_source_notes(lines: list[str], report: ReportData) -> None:
    lines.append("## Source Notes")
    lines.append(
        "JSON `items` entries include ticker, item_type, title, summary, why_it_matters, "
        "materiality, thesis_effect, confidence, freshness, source_quality, summary_confidence, "
        "source_name, source_url, final_url, aggregator_url, published_at, and fetched_at."
    )
    lines.append(
        "News is collected from configured APIs when available, then public RSS / Investor Relations "
        "fallbacks where possible. Missing source data is reported as `not available` or as warnings."
    )
    lines.append(
        "Google News RSS entries use `final_url` as the default report URL when resolved; "
        "`aggregator_url` preserves the original Google News RSS link."
    )
    lines.append("")


def _render_item(lines: list[str], item: IntelligenceItem) -> None:
    lines.append(f"- **{item.ticker} - {item.title}**")
    lines.append(
        f"  - item_type: {item.item_type}; materiality: {item.materiality}; "
        f"thesis_effect: {item.thesis_effect}; confidence: {item.confidence}; "
        f"summary_confidence: {item.summary_confidence}"
    )
    lines.append(
        f"  - freshness: {item.freshness}; source_quality: {item.source_quality}; "
        f"cluster_id: {_value(item.cluster_id)}; cluster_size: {item.cluster_size}"
    )
    lines.append(f"  - summary: {_value(item.summary)}")
    lines.append(f"  - why_it_matters: {_value(item.why_it_matters)}")
    if item.related_themes:
        lines.append(f"  - related_themes: {', '.join(item.related_themes)}")
    elif item.item_type in {"news", "public_news", "ir_news", "cn_announcement"}:
        lines.append("  - related_themes: not available")
    lines.append(
        f"  - source: {item.source_name}; published_at: {_value(item.published_at)}; "
        f"fetched_at: {item.fetched_at}; url: {_display_url(item)}"
    )
    if item.aggregator_url:
        lines.append(f"  - aggregator_url: {item.aggregator_url}")
    if item.cluster_sources:
        lines.append("  - cluster_sources:")
        for source in item.cluster_sources[:6]:
            lines.append(
                f"    - {source.publisher or source.source_name}; "
                f"quality={source.source_quality}; freshness={source.freshness}; "
                f"published_at={_value(source.published_at)}; url={source.final_url or source.source_url}"
            )


def _items_for_report(report: ReportData) -> list[IntelligenceItem]:
    if report.items:
        return report.items
    items: list[IntelligenceItem] = []
    items.extend(market_snapshot_to_item(snapshot) for snapshot in report.market_snapshot)
    items.extend(news_to_item(item) for item in report.news)
    items.extend(filing_to_item(item) for item in report.filings)
    items.extend(earnings_calendar_to_item(item) for item in report.earnings_calendar)
    return items


def _latest_snapshot_by_ticker(items: list[MarketSnapshot]) -> dict[str, MarketSnapshot]:
    latest: dict[str, MarketSnapshot] = {}
    for item in items:
        latest[item.ticker] = item
    return latest


def _value(value: object) -> str:
    if value is None or value == "":
        return "not available"
    return str(value)


def _display_url(item: IntelligenceItem) -> str:
    return item.final_url or item.source_url


def _number(value: float | None) -> str:
    return "not available" if value is None else f"{value:.2f}"


def _signed_number(value: float | None) -> str:
    return "not available" if value is None else f"{value:+.2f}"


def _integer(value: int | None) -> str:
    return "not available" if value is None else f"{value:,}"


def _escape(value: object) -> str:
    return _value(value).replace("|", "\\|")
