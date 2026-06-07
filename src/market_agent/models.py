from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


Materiality = Literal["high", "medium", "low"]
Freshness = Literal["fresh", "recent", "stale", "background", "unknown"]
SourceQuality = Literal["high", "medium", "low", "unknown"]
ThesisEffect = Literal[
    "supports_demand_thesis",
    "supports_pricing_power",
    "weakens_supply_shortage_thesis",
    "increases_competition_risk",
    "valuation_risk",
    "background_only",
    "needs_manual_review",
]
Confidence = Literal["high", "medium", "low"]


class StockItem(StrictModel):
    ticker: str
    name: str
    market: Literal["US", "CN"]
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
    keywords: list[str] = Field(default_factory=list)
    stocks: list[StockItem] = Field(min_length=1)


class SourceFields(StrictModel):
    source_name: str
    source_url: str
    final_url: str | None = None
    aggregator_url: str | None = None
    published_at: str | None = None
    fetched_at: str


class NewsClusterSource(StrictModel):
    source_name: str
    publisher: str | None = None
    source_url: str
    final_url: str | None = None
    aggregator_url: str | None = None
    source_quality: SourceQuality = "unknown"
    freshness: Freshness = "unknown"
    published_at: str | None = None


class MarketSnapshot(SourceFields):
    ticker: str
    name: str | None = None
    market: Literal["US", "CN"] | None = None
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
    item_type: str = "news"
    title: str
    summary: str | None = None
    summary_confidence: Confidence = "low"
    why_it_matters: str = "not available"
    related_themes: list[str] = Field(default_factory=list)
    materiality: Materiality = "low"
    thesis_effect: ThesisEffect = "needs_manual_review"
    confidence: Confidence = "medium"
    freshness: Freshness = "unknown"
    source_quality: SourceQuality = "unknown"
    publisher: str | None = None
    symbols: list[str] = Field(default_factory=list)
    manually_marked: bool = False
    cluster_id: str | None = None
    cluster_size: int = 1
    cluster_sources: list[NewsClusterSource] = Field(default_factory=list)
    core_claim: str | None = None

    @field_validator("thesis_effect", mode="before")
    @classmethod
    def normalize_news_thesis_effect(cls, value: object) -> str:
        return _normalize_thesis_effect(value)


class FilingItem(SourceFields):
    ticker: str
    form: str
    title: str | None = None
    summary: str | None = None
    materiality: Materiality = "low"
    why_it_matters: str = "not available"
    thesis_effect: ThesisEffect = "needs_manual_review"
    confidence: Confidence = "medium"
    filing_date: str | None = None
    accession_number: str | None = None
    description: str | None = None

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


class AlertItem(SourceFields):
    severity: Literal["info", "warning", "error"]
    message: str
    context: str | None = None


class IntelligenceItem(SourceFields):
    ticker: str
    item_type: str
    title: str
    summary: str
    summary_confidence: Confidence = "medium"
    why_it_matters: str
    related_themes: list[str] = Field(default_factory=list)
    materiality: Materiality
    thesis_effect: ThesisEffect
    confidence: Confidence
    freshness: Freshness = "unknown"
    source_quality: SourceQuality = "unknown"
    cluster_id: str | None = None
    cluster_size: int = 1
    cluster_sources: list[NewsClusterSource] = Field(default_factory=list)
    core_claim: str | None = None

    @field_validator("thesis_effect", mode="before")
    @classmethod
    def normalize_item_thesis_effect(cls, value: object) -> str:
        return _normalize_thesis_effect(value)


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
    freshness: Freshness = "unknown"
    source_url: str


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
    new_theme_mentions: list[str] = Field(default_factory=list)
    price_changes: list[PriceChange] = Field(default_factory=list)


class SourceRecord(StrictModel):
    record_type: str
    ticker: str | None = None
    title: str | None = None
    source_name: str
    source_url: str
    final_url: str | None = None
    aggregator_url: str | None = None
    source_quality: SourceQuality = "unknown"
    freshness: Freshness = "unknown"
    cluster_id: str | None = None
    published_at: str | None = None
    fetched_at: str


class ReportData(StrictModel):
    run_date: str
    timezone: str
    watchlist: list[StockItem] = Field(default_factory=list)
    market_snapshot: list[MarketSnapshot] = Field(default_factory=list)
    news: list[NewsItem] = Field(default_factory=list)
    filings: list[FilingItem] = Field(default_factory=list)
    earnings_calendar: list[EarningsCalendarItem] = Field(default_factory=list)
    earnings_transcripts: list[EarningsTranscriptItem] = Field(default_factory=list)
    theme_mentions: list[ThemeMention] = Field(default_factory=list)
    alerts: list[AlertItem] = Field(default_factory=list)
    changes_since_last_report: ReportChanges = Field(default_factory=ReportChanges)
    items: list[IntelligenceItem] = Field(default_factory=list)
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
    if text in {
        "supports_demand_thesis",
        "supports_pricing_power",
        "weakens_supply_shortage_thesis",
        "increases_competition_risk",
        "valuation_risk",
        "background_only",
        "needs_manual_review",
    }:
        return text
    legacy_map = {
        "positive": "supports_demand_thesis",
        "negative": "needs_manual_review",
        "mixed": "needs_manual_review",
        "neutral": "background_only",
        "unknown": "needs_manual_review",
        "": "needs_manual_review",
    }
    return legacy_map.get(text.casefold(), "needs_manual_review")
