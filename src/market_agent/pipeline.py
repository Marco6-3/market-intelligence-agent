from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import yaml

from .cache import FileCache
from .config import AppConfig
from .intelligence import (
    build_analyst_review_queue,
    cluster_news_items,
    earnings_calendar_to_item,
    enrich_news_item,
    filing_to_item,
    market_snapshot_to_item,
    news_to_item,
    related_themes_for_text,
    theme_terms_for_stock,
)
from .models import (
    AlertItem,
    EarningsCalendarItem,
    FilingItem,
    IntelligenceItem,
    MarketSnapshot,
    NewsItem,
    PriceChange,
    ReportData,
    ReportChanges,
    SourceFields,
    SourceRecord,
    StockItem,
    ThemeMention,
    Watchlist,
)
from .renderers.csv_sources import write_sources_csv
from .renderers.json_export import write_json_report
from .renderers.markdown import render_markdown
from .sources.akshare_cn import AkshareCNClient
from .sources.alpha_vantage import AlphaVantageClient
from .sources.finnhub import FinnhubClient
from .sources.fmp import FMPClient
from .sources.public_news import PublicNewsClient
from .sources.sec_edgar import SECEdgarClient
from .sources.tushare_cn import TushareCNClient
from .sources.yfinance_us import YFinanceClient
from .utils.text import truncate
from .utils.time import parse_run_date, utc_now_iso


@dataclass(frozen=True)
class PipelineResult:
    report: ReportData
    markdown_path: Path
    json_path: Path
    sources_csv_path: Path
    warnings: list[str]


def load_watchlist(path: Path) -> Watchlist:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Watchlist must be a YAML mapping: {path}")
    return Watchlist.model_validate(data)


def run_daily_brief(
    watchlist_path: Path,
    run_date: str | None = None,
    output_dir: Path = Path("reports"),
    cache_dir: Path = Path("data_cache"),
) -> PipelineResult:
    watchlist_path = watchlist_path.resolve()
    base_dir = watchlist_path.parent
    output_dir = output_dir if output_dir.is_absolute() else base_dir / output_dir
    cache_dir = cache_dir if cache_dir.is_absolute() else base_dir / cache_dir

    watchlist = load_watchlist(watchlist_path)
    report_date = parse_run_date(run_date, watchlist.timezone)
    config = AppConfig.from_env(base_dir / ".env")
    cache = FileCache(cache_dir, ttl_seconds=config.cache_ttl_seconds)

    warnings: list[str] = []
    warned_keys: set[str] = set()
    alerts: list[AlertItem] = []
    market_snapshot: list[MarketSnapshot] = []
    news: list[NewsItem] = []
    filings: list[FilingItem] = []
    earnings_calendar: list[EarningsCalendarItem] = []

    fmp_client = FMPClient(config.fmp_api_key, cache) if config.fmp_api_key else None
    alpha_client = (
        AlphaVantageClient(config.alpha_vantage_api_key, cache)
        if config.alpha_vantage_api_key
        else None
    )
    finnhub_client = FinnhubClient(config.finnhub_api_key, cache) if config.finnhub_api_key else None
    sec_client = SECEdgarClient(config.sec_user_agent, cache)
    yfinance_client = YFinanceClient() if config.yfinance_enabled else None
    akshare_client = AkshareCNClient()
    tushare_client = TushareCNClient(config.tushare_token) if config.tushare_token else None
    public_news_client = PublicNewsClient(cache)

    news_start = report_date - timedelta(days=7)
    calendar_end = report_date + timedelta(days=30)

    for stock in watchlist.stocks:
        if stock.market == "US":
            stock_news: list[NewsItem] = []
            stock_earnings: list[EarningsCalendarItem] = []

            if yfinance_client:
                market_snapshot.extend(
                    _safe_collect(
                        lambda: yfinance_client.fetch_quote(stock),
                        "yfinance quote",
                        stock.ticker,
                        alerts,
                        warnings,
                    )
                )
            else:
                _warn_once(
                    "yfinance_disabled",
                    "YFINANCE_ENABLED is false; skipping yfinance US market snapshots.",
                    warned_keys,
                    alerts,
                    warnings,
                )

            if fmp_client:
                stock_news.extend(
                    _safe_collect(
                        lambda: fmp_client.fetch_stock_news(stock.ticker),
                        "FMP news",
                        stock.ticker,
                        alerts,
                        warnings,
                    )
                )
            else:
                _warn_once(
                    "missing_fmp",
                    "FMP_API_KEY is not configured; using public/RSS news fallback where possible.",
                    warned_keys,
                    alerts,
                    warnings,
                )

            if not stock_news:
                if alpha_client:
                    stock_news.extend(
                        _safe_collect(
                            lambda: alpha_client.fetch_news(stock.ticker),
                            "Alpha Vantage news",
                            stock.ticker,
                            alerts,
                            warnings,
                        )
                    )
                elif finnhub_client:
                    stock_news.extend(
                        _safe_collect(
                            lambda: finnhub_client.fetch_company_news(
                                stock.ticker, news_start, report_date
                            ),
                            "Finnhub news",
                            stock.ticker,
                            alerts,
                            warnings,
                        )
                    )
                else:
                    _warn_once(
                        "missing_us_news_fallbacks",
                        "No API-key US news fallback configured; trying public Google News RSS and Investor Relations RSS.",
                        warned_keys,
                        alerts,
                        warnings,
                    )

            if not stock_news:
                stock_news.extend(
                    _safe_collect(
                        lambda: public_news_client.fetch_company_news(
                            stock, theme_terms_for_stock(stock, watchlist.keywords)
                        ),
                        "public Google News RSS",
                        stock.ticker,
                        alerts,
                        warnings,
                    )
                )
            stock_news.extend(
                _safe_collect(
                    lambda: public_news_client.fetch_ir_news(stock),
                    "Investor Relations RSS",
                    stock.ticker,
                    alerts,
                    warnings,
                )
            )

            if not stock_earnings:
                if alpha_client:
                    stock_earnings.extend(
                        _safe_collect(
                            lambda: alpha_client.fetch_earnings_calendar(
                                stock.ticker, report_date, calendar_end
                            ),
                            "Alpha Vantage earnings calendar",
                            stock.ticker,
                            alerts,
                            warnings,
                        )
                    )
                if not stock_earnings and finnhub_client:
                    stock_earnings.extend(
                        _safe_collect(
                            lambda: finnhub_client.fetch_earnings_calendar(
                                stock.ticker, report_date, calendar_end
                            ),
                            "Finnhub earnings calendar",
                            stock.ticker,
                            alerts,
                            warnings,
                        )
                    )
                if not stock_earnings and fmp_client:
                    stock_earnings.extend(
                        _safe_collect(
                            lambda: fmp_client.fetch_earnings_calendar(
                                stock.ticker, report_date, calendar_end
                            ),
                            "FMP earnings calendar fallback",
                            stock.ticker,
                            alerts,
                            warnings,
                        )
                    )
                if not stock_earnings and not any([alpha_client, finnhub_client, fmp_client]):
                    _warn_earnings_unavailable(
                        stock.ticker,
                        (
                            "ALPHA_VANTAGE_API_KEY and FINNHUB_API_KEY are not configured, "
                            "and FMP_API_KEY fallback is unavailable"
                        ),
                        alerts,
                        warnings,
                    )

            _mark_earnings_alerts(stock_earnings, report_date, alerts)
            news.extend(stock_news)
            earnings_calendar.extend(stock_earnings)
            filings.extend(
                _safe_collect(
                    lambda: sec_client.fetch_recent_filings(stock.ticker),
                    "SEC EDGAR filings",
                    stock.ticker,
                    alerts,
                    warnings,
                )
            )

        elif stock.market == "CN":
            market_snapshot.extend(
                _safe_collect(
                    lambda: akshare_client.fetch_snapshot(stock),
                    "AKShare CN snapshot",
                    stock.ticker,
                    alerts,
                    warnings,
                )
            )
            news.extend(
                _safe_collect(
                    lambda: akshare_client.fetch_announcements(stock),
                    "AKShare CN announcements",
                    stock.ticker,
                    alerts,
                    warnings,
                )
            )
            if tushare_client:
                market_snapshot.extend(
                    _safe_collect(
                        lambda: tushare_client.fetch_recent_daily(stock, report_date),
                        "Tushare CN daily",
                        stock.ticker,
                        alerts,
                        warnings,
                    )
                )
            else:
                _warn_once(
                    "missing_tushare",
                    "TUSHARE_TOKEN is not configured; skipping Tushare CN source.",
                    warned_keys,
                    alerts,
                    warnings,
                )

    news = _enrich_news_items(news, watchlist.stocks, watchlist.keywords, report_date)
    theme_mentions = _build_theme_mentions(watchlist.stocks, watchlist.keywords, news, filings)
    questions = _build_questions(watchlist.stocks, watchlist.keywords)

    report = ReportData(
        run_date=report_date.isoformat(),
        timezone=watchlist.timezone,
        watchlist=watchlist.stocks,
        market_snapshot=market_snapshot,
        news=news,
        filings=filings,
        earnings_calendar=earnings_calendar,
        earnings_transcripts=[],
        theme_mentions=theme_mentions,
        alerts=alerts,
        questions_for_analysis=questions,
        sources=[],
    )
    report.items = _build_intelligence_items(report)
    report.analyst_review_queue = build_analyst_review_queue(report.items)
    report.changes_since_last_report = _build_changes_since_last_report(report, output_dir)
    report.sources = _build_source_records(report)

    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / f"{report.run_date}_daily_brief.md"
    json_path = output_dir / f"{report.run_date}_daily_brief.json"
    sources_csv_path = output_dir / f"{report.run_date}_sources.csv"

    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    write_json_report(report, json_path)
    write_sources_csv(report, sources_csv_path)

    return PipelineResult(
        report=report,
        markdown_path=markdown_path,
        json_path=json_path,
        sources_csv_path=sources_csv_path,
        warnings=warnings,
    )


def _safe_collect(
    fetcher: object,
    source_name: str,
    ticker: str,
    alerts: list[AlertItem],
    warnings: list[str],
) -> list:
    try:
        return list(fetcher())
    except Exception as exc:
        message = f"{source_name} failed for {ticker}: {exc}"
        warnings.append(message)
        alerts.append(
            AlertItem(
                severity="warning",
                message=message,
                context=ticker,
                source_name=source_name,
                source_url="not available",
                published_at=None,
                fetched_at=utc_now_iso(),
            )
        )
        return []


def _warn_once(
    key: str,
    message: str,
    warned_keys: set[str],
    alerts: list[AlertItem],
    warnings: list[str],
) -> None:
    if key in warned_keys:
        return
    warned_keys.add(key)
    warnings.append(message)
    alerts.append(
        AlertItem(
            severity="warning",
            message=message,
            context=None,
            source_name="configuration",
            source_url="not available",
            published_at=None,
            fetched_at=utc_now_iso(),
        )
    )


def _warn_earnings_unavailable(
    ticker: str,
    reason: str,
    alerts: list[AlertItem],
    warnings: list[str],
) -> None:
    message = f"earnings calendar unavailable because {reason}."
    warnings.append(f"{ticker}: {message}")
    alerts.append(
        AlertItem(
            severity="warning",
            message=message,
            context=ticker,
            source_name="earnings_calendar",
            source_url="not available",
            published_at=None,
            fetched_at=utc_now_iso(),
        )
    )


def _mark_earnings_alerts(
    items: list[EarningsCalendarItem],
    report_date: date,
    alerts: list[AlertItem],
) -> None:
    for index, item in enumerate(items):
        report_day = _date_from_iso_prefix(item.report_date)
        if report_day is None:
            continue
        days_until = (report_day - report_date).days
        if 0 <= days_until <= 30:
            items[index] = item.model_copy(
                update={"days_until_report": days_until, "earnings_alert": True}
            )
            alerts.append(
                AlertItem(
                    severity="info",
                    message=(
                        f"earnings_alert: {item.ticker} reports on {report_day.isoformat()} "
                        f"({days_until} days from report_date)."
                    ),
                    context=item.ticker,
                    source_name=item.source_name,
                    source_url=item.source_url,
                    final_url=item.final_url,
                    aggregator_url=item.aggregator_url,
                    published_at=item.published_at,
                    fetched_at=utc_now_iso(),
                )
            )


def _date_from_iso_prefix(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _enrich_news_items(
    news: list[NewsItem],
    stocks: Iterable[StockItem],
    global_keywords: list[str],
    report_date: date,
) -> list[NewsItem]:
    stocks_by_ticker = {stock.ticker: stock for stock in stocks}
    enriched: list[NewsItem] = []
    for item in news:
        stock = stocks_by_ticker.get(item.ticker)
        if stock:
            enriched.append(enrich_news_item(item, stock, global_keywords, report_date))
        else:
            enriched.append(item)
    return cluster_news_items(_dedupe_news_items(enriched))


def _dedupe_news_items(news: list[NewsItem]) -> list[NewsItem]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[NewsItem] = []
    for item in news:
        key = (item.ticker.upper(), item.title.casefold(), item.source_url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _build_theme_mentions(
    stocks: Iterable[StockItem],
    global_keywords: list[str],
    news: list[NewsItem],
    filings: list[FilingItem],
) -> list[ThemeMention]:
    mentions: list[ThemeMention] = []
    stocks_by_ticker = {stock.ticker: stock for stock in stocks}
    for item in news:
        stock = stocks_by_ticker.get(item.ticker)
        if not stock:
            continue
        matched_terms = item.related_themes or related_themes_for_text(
            item.title,
            item.summary,
            theme_terms_for_stock(stock, global_keywords),
        )
        for term_clean in matched_terms:
            mentions.append(
                ThemeMention(
                    ticker=item.ticker,
                    theme=term_clean,
                    item_type="news",
                    title=item.title,
                    snippet=truncate(item.summary, 240),
                    source_name=item.source_name,
                    source_url=item.source_url,
                    published_at=item.published_at,
                    fetched_at=item.fetched_at,
                )
            )
    for item in filings:
        stock = stocks_by_ticker.get(item.ticker)
        if not stock:
            continue
        matched_terms = related_themes_for_text(
            item.title or item.form,
            f"{item.summary or ''} {item.description or ''}",
            theme_terms_for_stock(stock, global_keywords),
        )
        for term_clean in matched_terms:
            mentions.append(
                ThemeMention(
                    ticker=item.ticker,
                    theme=term_clean,
                    item_type="sec_filing",
                    title=item.title or item.form,
                    snippet=truncate(item.summary or item.description, 240),
                    source_name=item.source_name,
                    source_url=item.source_url,
                    published_at=item.published_at,
                    fetched_at=item.fetched_at,
                )
            )
    return mentions


def _build_intelligence_items(report: ReportData) -> list[IntelligenceItem]:
    items: list[IntelligenceItem] = []
    items.extend(market_snapshot_to_item(snapshot) for snapshot in report.market_snapshot)
    items.extend(news_to_item(item) for item in report.news)
    items.extend(filing_to_item(item) for item in report.filings)
    items.extend(earnings_calendar_to_item(item) for item in report.earnings_calendar)
    return sorted(items, key=_item_sort_key)


def _item_sort_key(item: IntelligenceItem) -> tuple[int, str, str]:
    materiality_rank = {"high": 0, "medium": 1, "low": 2}
    published = item.published_at or ""
    return (materiality_rank.get(item.materiality, 9), item.ticker, published)


def _build_changes_since_last_report(report: ReportData, output_dir: Path) -> ReportChanges:
    previous_path = _find_previous_report_path(output_dir, date.fromisoformat(report.run_date))
    if previous_path is None:
        return ReportChanges()
    previous = _load_previous_report(previous_path)
    if previous is None:
        return ReportChanges(
            status=f"Previous report found but could not be parsed: {previous_path.name}",
            previous_report_path=str(previous_path),
        )

    previous_filing_keys = {_filing_key(item) for item in previous.filings}
    previous_news_keys = {_news_key(item) for item in previous.news}
    previous_theme_keys = {_theme_key(item) for item in previous.theme_mentions}

    new_filings = [
        filing_to_item(item)
        for item in report.filings
        if _filing_key(item) not in previous_filing_keys
    ]
    new_news = [news_to_item(item) for item in report.news if _news_key(item) not in previous_news_keys]
    new_theme_mentions = [
        f"{item.ticker}: {item.theme} - {item.title}"
        for item in report.theme_mentions
        if _theme_key(item) not in previous_theme_keys
    ]

    return ReportChanges(
        status=f"Compared with previous report {previous.run_date}",
        previous_report_path=str(previous_path),
        new_filings=new_filings,
        new_news=new_news,
        new_theme_mentions=new_theme_mentions,
        price_changes=_build_price_changes(previous, report),
    )


def _find_previous_report_path(output_dir: Path, report_date: date) -> Path | None:
    if not output_dir.exists():
        return None
    candidates: list[tuple[date, Path]] = []
    for path in output_dir.glob("*_daily_brief.json"):
        date_part = path.name.removesuffix("_daily_brief.json")
        try:
            candidate_date = date.fromisoformat(date_part)
        except ValueError:
            continue
        if candidate_date < report_date:
            candidates.append((candidate_date, path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _load_previous_report(path: Path) -> ReportData | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ReportData.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _build_price_changes(previous: ReportData, current: ReportData) -> list[PriceChange]:
    previous_by_ticker = _latest_snapshot_by_ticker(previous.market_snapshot)
    current_by_ticker = _latest_snapshot_by_ticker(current.market_snapshot)
    changes: list[PriceChange] = []
    for ticker, current_snapshot in current_by_ticker.items():
        previous_snapshot = previous_by_ticker.get(ticker)
        if not previous_snapshot:
            continue
        previous_price = previous_snapshot.price
        current_price = current_snapshot.price
        price_change = None
        change_percent = None
        if previous_price is not None and current_price is not None:
            price_change = current_price - previous_price
            if previous_price != 0:
                change_percent = (price_change / previous_price) * 100
        changes.append(
            PriceChange(
                ticker=ticker,
                previous_price=previous_price,
                current_price=current_price,
                price_change=price_change,
                change_percent=change_percent,
                previous_report_date=previous.run_date,
                current_report_date=current.run_date,
            )
        )
    return changes


def _latest_snapshot_by_ticker(items: Iterable[MarketSnapshot]) -> dict[str, MarketSnapshot]:
    result: dict[str, MarketSnapshot] = {}
    for item in items:
        result[item.ticker] = item
    return result


def _filing_key(item: FilingItem) -> tuple[str, str, str]:
    return (
        item.ticker.upper(),
        item.accession_number or item.source_url,
        item.form.upper(),
    )


def _news_key(item: NewsItem) -> tuple[str, str, str]:
    return (item.ticker.upper(), item.source_url, item.title.casefold())


def _theme_key(item: ThemeMention) -> tuple[str, str, str, str]:
    return (
        item.ticker.upper(),
        item.theme.casefold(),
        item.item_type,
        item.source_url,
    )


def _build_questions(stocks: Iterable[StockItem], keywords: list[str]) -> list[str]:
    stocks_list = list(stocks)
    tickers = ", ".join(stock.ticker for stock in stocks_list)
    all_terms: list[str] = []
    seen: set[str] = set()
    for stock in stocks_list:
        for term in theme_terms_for_stock(stock, keywords):
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            all_terms.append(term)
    theme_text = ", ".join(all_terms[:16]) if all_terms else "the configured stock themes"
    return [
        f"Which collected items are most material for {tickers}, and why?",
        f"Do the filings, earnings calendar items, and news create any contradictions or open questions for {tickers}?",
        f"What follow-up evidence should be gathered for themes: {theme_text}?",
        "Which claims in the report are weak because the underlying source data is missing or stale?",
    ]


def _build_source_records(report: ReportData) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    records.extend(_records_from_items("market_snapshot", report.market_snapshot))
    records.extend(_records_from_items("news", report.news))
    records.extend(_records_from_items("filing", report.filings))
    records.extend(_records_from_items("earnings_calendar", report.earnings_calendar))
    records.extend(_records_from_items("earnings_transcript", report.earnings_transcripts))
    records.extend(_records_from_items("theme_mention", report.theme_mentions))
    records.extend(_records_from_items("alert", report.alerts))
    records.extend(_records_from_items("intelligence_item", report.items))
    return records


def _records_from_items(record_type: str, items: Iterable[SourceFields]) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for item in items:
        title = getattr(item, "title", None) or getattr(item, "form", None) or getattr(item, "message", None)
        records.append(
            SourceRecord(
                record_type=record_type,
                ticker=getattr(item, "ticker", None),
                title=truncate(title, 240),
                source_name=item.source_name,
                source_url=item.source_url,
                final_url=getattr(item, "final_url", None),
                aggregator_url=getattr(item, "aggregator_url", None),
                source_quality=getattr(item, "source_quality", "unknown"),
                freshness=getattr(item, "freshness", "unknown"),
                cluster_id=getattr(item, "cluster_id", None),
                published_at=item.published_at,
                fetched_at=item.fetched_at,
            )
        )
    return records
