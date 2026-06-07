from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


Materiality = Literal["high", "medium", "low"]
FreshnessLabel = Literal["fresh", "recent", "stale_context", "unknown"]
SourceQuality = Literal["high", "medium", "low", "unknown"]
ContentDepth = Literal["headline_only", "article_excerpt", "full_article"]
CanonicalUrlStatus = Literal["resolved", "unavailable", "failed"]
ThesisEffect = Literal[
    "supports_thesis",
    "weakens_thesis",
    "neutral",
    "unknown",
    "needs_review",
]
Confidence = Literal["high", "medium", "low"]
WatchlistScope = Literal["daily", "weekly", "all"]


class ReportPolicy(StrictModel):
    max_items_per_ticker: int = 5
    max_news_per_ticker: int = 3
    max_critical_alerts_per_day: int = 10
    max_low_materiality_items: int = 20
    only_show_fresh_news_days: int = 7
    stale_news_days: int = 14
    weekly_extended_watchlist_day: str = "Sunday"


class GlobalSettings(StrictModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    enable_public_news_fallback: bool = True
    enable_google_news_rss: bool = True
    enable_investor_relations_rss: bool = True
    enable_sec_edgar: bool = True
    enable_yfinance: bool = True
    no_buy_sell_recommendations: bool = True


class StockItem(StrictModel):
    ticker: str
    name: str
    market: str
    category: str = "Uncategorized"
    aliases: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    ir_news_urls: list[str] = Field(default_factory=list)

    @field_validator("ticker", "name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("market", mode="before")
    @classmethod
    def normalize_market(cls, value: str) -> str:
        return str(value).strip().upper()


class Watchlist(StrictModel):
    timezone: str = "Asia/Singapore"
    report_policy: ReportPolicy = Field(default_factory=ReportPolicy)
    global_settings: GlobalSettings = Field(default_factory=GlobalSettings)
    keywords: list[str] = Field(default_factory=list)
    stocks: list[StockItem] = Field(default_factory=list)
    daily_core_stocks: list[StockItem] = Field(default_factory=list)
    weekly_extended_stocks: list[StockItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def drop_legacy_out_of_scope_lists(cls, data: object) -> object:
        if isinstance(data, dict):
            cleaned = dict(data)
            cleaned.pop("china_weekly_stocks", None)
            return cleaned
        return data

    @model_validator(mode="after")
    def require_some_stocks(self) -> "Watchlist":
        if not any([self.stocks, self.daily_core_stocks, self.weekly_extended_stocks]):
            raise ValueError("watchlist must define stocks or scoped stock lists")
        return self


class SummaryFields(StrictModel):
    what_happened: str = "not available"
    affected_company: str = "not available"
    related_theme: str = "not available"
    possible_financial_impact: str = "not available"
    evidence_strength: Confidence = "low"
    follow_up_needed: str = "not available"

    @classmethod
    def from_text(
        cls,
        text: object,
        *,
        affected_company: object = None,
        related_theme: object = None,
        evidence_strength: Confidence = "low",
        follow_up_needed: object = None,
    ) -> "SummaryFields":
        cleaned = str(text or "").strip() or "not available"
        return cls(
            what_happened=cleaned,
            affected_company=str(affected_company or "not available"),
            related_theme=str(related_theme or "not available"),
            possible_financial_impact="not available",
            evidence_strength=evidence_strength,
            follow_up_needed=str(follow_up_needed or "Verify with primary source or full article."),
        )


class FreshnessInfo(StrictModel):
    published_days_ago: int | None = None
    is_newly_published: bool = False
    is_newly_discovered: bool = False
    freshness_label: FreshnessLabel = "unknown"


class SourceFields(StrictModel):
    source_name: str
    source_url: str
    final_url: str | None = None
    canonical_url: str | None = None
    canonical_url_status: CanonicalUrlStatus = "unavailable"
    aggregator_source: str | None = None
    aggregator_url: str | None = None
    published_at: str | None = None
    fetched_at: str


class NewsClusterSource(StrictModel):
    source_name: str
    publisher: str | None = None
    source_url: str
    final_url: str | None = None
    canonical_url: str | None = None
    aggregator_source: str | None = None
    aggregator_url: str | None = None
    source_quality: SourceQuality = "unknown"
    freshness: FreshnessInfo = Field(default_factory=FreshnessInfo)
    published_at: str | None = None


class MarketSnapshot(SourceFields):
    ticker: str
    name: str | None = None
    market: str | None = None
    price: float | None = None
    currency: str | None = None
    change_percent: float | None = None
    previous_close: float | None = None
    open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    volume: int | None = None
    avg_volume: int | None = None
    market_cap: int | None = None
    week_52_high: float | None = Field(default=None, alias="52_week_high")
    week_52_low: float | None = Field(default=None, alias="52_week_low")
    data_timestamp: str | None = None
    observed_at: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "price",
        "change_percent",
        "previous_close",
        "open",
        "day_high",
        "day_low",
        "week_52_high",
        "week_52_low",
        mode="before",
    )
    @classmethod
    def round_price_fields(cls, value: object) -> float | None:
        return _round_float(value, digits=2)

    @field_validator("volume", "avg_volume", "market_cap", mode="before")
    @classmethod
    def coerce_large_int_fields(cls, value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return None

    @field_validator("raw", mode="before")
    @classmethod
    def sanitize_raw_payload(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {str(key): _json_safe_value(raw_value) for key, raw_value in value.items()}


class NewsItem(SourceFields):
    ticker: str
    company_name: str = "not available"
    category: str = "Uncategorized"
    item_type: str = "public_news"
    title: str
    summary: SummaryFields = Field(default_factory=SummaryFields)
    summary_confidence: Confidence = "low"
    why_it_matters: str = "not available"
    related_themes: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    materiality: Materiality = "low"
    materiality_score: int = 0
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    thesis_effect: ThesisEffect = "needs_review"
    confidence: Confidence = "medium"
    freshness: FreshnessInfo = Field(default_factory=FreshnessInfo)
    content_depth: ContentDepth = "headline_only"
    source_quality: SourceQuality = "unknown"
    publisher: str | None = None
    symbols: list[str] = Field(default_factory=list)
    manually_marked: bool = False
    cluster_id: str | None = None
    cluster_size: int = 1
    cluster_sources: list[NewsClusterSource] = Field(default_factory=list)
    core_claim: str | None = None
    is_duplicate: bool = False

    @field_validator("summary", mode="before")
    @classmethod
    def coerce_summary(cls, value: object) -> SummaryFields:
        if isinstance(value, SummaryFields):
            return value
        if isinstance(value, dict):
            return SummaryFields.model_validate(value)
        return SummaryFields.from_text(value)

    @field_validator("thesis_effect", mode="before")
    @classmethod
    def normalize_news_thesis_effect(cls, value: object) -> str:
        return _normalize_thesis_effect(value)


class FilingItem(SourceFields):
    ticker: str
    company_name: str = "not available"
    category: str = "Uncategorized"
    form: str
    title: str | None = None
    summary: SummaryFields = Field(default_factory=SummaryFields)
    materiality: Materiality = "low"
    materiality_score: int = 0
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    why_it_matters: str = "not available"
    thesis_effect: ThesisEffect = "needs_review"
    confidence: Confidence = "medium"
    freshness: FreshnessInfo = Field(default_factory=FreshnessInfo)
    content_depth: ContentDepth = "article_excerpt"
    source_quality: SourceQuality = "high"
    related_themes: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    filing_date: str | None = None
    accession_number: str | None = None
    description: str | None = None

    @field_validator("summary", mode="before")
    @classmethod
    def coerce_summary(cls, value: object) -> SummaryFields:
        if isinstance(value, SummaryFields):
            return value
        if isinstance(value, dict):
            return SummaryFields.model_validate(value)
        return SummaryFields.from_text(value, evidence_strength="high")

    @field_validator("thesis_effect", mode="before")
    @classmethod
    def normalize_filing_thesis_effect(cls, value: object) -> str:
        return _normalize_thesis_effect(value)


class EarningsCalendarItem(SourceFields):
    ticker: str
    report_date: str | None = None
    fiscal_date: str | None = None
    eps_estimate: float | None = None
    revenue_estimate: float | None = None
    time: str | None = None
    days_until_report: int | None = None
    earnings_alert: bool = False


class EarningsTranscriptItem(SourceFields):
    ticker: str
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    title: str | None = None
    transcript_excerpt: str | None = None


class ThemeMention(SourceFields):
    ticker: str
    theme: str
    item_type: str
    title: str
    snippet: str | None = None
    matched_terms: list[str] = Field(default_factory=list)
    freshness: FreshnessInfo = Field(default_factory=FreshnessInfo)


class AlertItem(SourceFields):
    severity: Literal["info", "warning", "error"]
    message: str
    context: str | None = None


class IntelligenceItem(SourceFields):
    ticker: str
    company_name: str = "not available"
    category: str = "Uncategorized"
    item_type: str
    title: str
    summary: SummaryFields = Field(default_factory=SummaryFields)
    summary_confidence: Confidence = "medium"
    why_it_matters: str
    related_themes: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    materiality: Materiality
    materiality_score: int = 0
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    thesis_effect: ThesisEffect
    confidence: Confidence
    freshness: FreshnessInfo = Field(default_factory=FreshnessInfo)
    content_depth: ContentDepth = "article_excerpt"
    source_quality: SourceQuality = "unknown"
    cluster_id: str | None = None
    cluster_size: int = 1
    cluster_sources: list[NewsClusterSource] = Field(default_factory=list)
    core_claim: str | None = None
    is_duplicate: bool = False

    @field_validator("summary", mode="before")
    @classmethod
    def coerce_summary(cls, value: object) -> SummaryFields:
        if isinstance(value, SummaryFields):
            return value
        if isinstance(value, dict):
            return SummaryFields.model_validate(value)
        return SummaryFields.from_text(value)

    @field_validator("thesis_effect", mode="before")
    @classmethod
    def normalize_item_thesis_effect(cls, value: object) -> str:
        return _normalize_thesis_effect(value)


class NewsCluster(StrictModel):
    cluster_id: str
    primary_title: str
    tickers: list[str] = Field(default_factory=list)
    related_themes: list[str] = Field(default_factory=list)
    source_count: int = 0
    best_source: str = "not available"
    newest_published_at: str | None = None
    items: list[dict[str, Any]] = Field(default_factory=list)


class AnalystTriageItem(StrictModel):
    ticker: str
    title: str
    reason: str
    follow_up_needed: str
    materiality: Materiality
    materiality_score: int
    freshness_label: FreshnessLabel
    evidence_strength: Confidence
    source_url: str


class AnalystTriage(StrictModel):
    must_review_today: list[AnalystTriageItem] = Field(default_factory=list)
    watch_items: list[AnalystTriageItem] = Field(default_factory=list)
    background_context: list[AnalystTriageItem] = Field(default_factory=list)
    noise_duplicate_low_confidence: list[AnalystTriageItem] = Field(default_factory=list)


class AnalystReviewQueueItem(StrictModel):
    ticker: str
    core_claim: str
    why_it_matters: str
    evidence_strength: str
    possible_thesis_effect: ThesisEffect
    follow_up_questions: list[str] = Field(default_factory=list)
    item_type: str
    materiality: Materiality
    source_quality: SourceQuality = "unknown"
    freshness: FreshnessInfo = Field(default_factory=FreshnessInfo)
    source_url: str


class CategorySummary(StrictModel):
    category: str
    key_movers: list[str] = Field(default_factory=list)
    important_news: list[str] = Field(default_factory=list)
    demand_signal: str = "not available"
    risk_signal: str = "not available"
    evidence_strength: Confidence = "low"


class PriceChange(StrictModel):
    ticker: str
    previous_price: float | None = None
    current_price: float | None = None
    price_change: float | None = None
    change_percent: float | None = None
    previous_report_date: str | None = None
    current_report_date: str | None = None

    @field_validator("previous_price", "current_price", "price_change", "change_percent", mode="before")
    @classmethod
    def round_change_fields(cls, value: object) -> float | None:
        return _round_float(value, digits=2)


class ReportChanges(StrictModel):
    status: str = "No previous report found"
    previous_report_path: str | None = None
    new_filings: list[IntelligenceItem] = Field(default_factory=list)
    new_news: list[IntelligenceItem] = Field(default_factory=list)
    newly_published: list[IntelligenceItem] = Field(default_factory=list)
    newly_discovered_stale: list[IntelligenceItem] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    new_theme_mentions: list[str] = Field(default_factory=list)
    removed_or_no_longer_active_alerts: list[str] = Field(default_factory=list)
    price_changes: list[PriceChange] = Field(default_factory=list)


class SourceRecord(StrictModel):
    record_type: str
    ticker: str | None = None
    title: str | None = None
    source_name: str
    source_url: str
    final_url: str | None = None
    canonical_url: str | None = None
    canonical_url_status: CanonicalUrlStatus = "unavailable"
    aggregator_source: str | None = None
    aggregator_url: str | None = None
    source_quality: SourceQuality = "unknown"
    freshness: FreshnessInfo = Field(default_factory=FreshnessInfo)
    cluster_id: str | None = None
    content_depth: ContentDepth | None = None
    published_at: str | None = None
    fetched_at: str


class ReportData(StrictModel):
    run_date: str
    timezone: str
    scope: WatchlistScope = "daily"
    watchlist: list[StockItem] = Field(default_factory=list)
    market_snapshot: list[MarketSnapshot] = Field(default_factory=list)
    news: list[NewsItem] = Field(default_factory=list)
    items: list[IntelligenceItem] = Field(default_factory=list)
    news_clusters: list[NewsCluster] = Field(default_factory=list)
    filings: list[FilingItem] = Field(default_factory=list)
    earnings_calendar: list[EarningsCalendarItem] = Field(default_factory=list)
    earnings_transcripts: list[EarningsTranscriptItem] = Field(default_factory=list)
    theme_mentions: list[ThemeMention] = Field(default_factory=list)
    category_summary: list[CategorySummary] = Field(default_factory=list)
    analyst_triage: AnalystTriage = Field(default_factory=AnalystTriage)
    alerts: list[AlertItem] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    changes_since_last_report: ReportChanges = Field(default_factory=ReportChanges)
    analyst_review_queue: list[AnalystReviewQueueItem] = Field(default_factory=list)
    questions_for_analysis: list[str] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)


def _round_float(value: object, digits: int) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _json_safe_value(value: object) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return round(value, 2)
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return str(value)


def _normalize_thesis_effect(value: object) -> str:
    text = str(value or "").strip()
    if text in {"supports_thesis", "weakens_thesis", "neutral", "unknown", "needs_review"}:
        return text
    legacy_map = {
        "supports_demand_thesis": "supports_thesis",
        "supports_pricing_power": "supports_thesis",
        "weakens_supply_shortage_thesis": "weakens_thesis",
        "increases_competition_risk": "weakens_thesis",
        "valuation_risk": "needs_review",
        "background_only": "neutral",
        "needs_manual_review": "needs_review",
        "positive": "supports_thesis",
        "negative": "weakens_thesis",
        "mixed": "needs_review",
        "neutral": "neutral",
        "unknown": "unknown",
        "": "needs_review",
    }
    return legacy_map.get(text.casefold(), "needs_review")
