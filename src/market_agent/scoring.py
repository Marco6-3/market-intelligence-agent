from __future__ import annotations

from typing import Iterable, Protocol

from .freshness import freshness_label
from .models import FreshnessInfo, Materiality, SummaryFields
from .utils.text import clean_text


class ScorableItem(Protocol):
    ticker: str
    title: str
    item_type: str
    source_name: str
    source_url: str
    published_at: str | None
    freshness: FreshnessInfo
    related_themes: list[str]
    content_depth: str
    summary: SummaryFields


MAJOR_REPUTABLE_NEWS = {
    "reuters",
    "bloomberg",
    "the wall street journal",
    "wall street journal",
    "wsj",
    "nikkei",
    "financial times",
    "ft",
    "cnbc",
}

FINANCIAL_IMPACT_TERMS = {
    "earnings",
    "guidance",
    "revenue",
    "margin",
    "order",
    "orders",
    "capex",
    "pricing",
    "price",
    "supply",
    "demand",
    "profit",
    "loss",
    "cash flow",
    "free cash flow",
    "业绩",
    "营收",
    "利润",
    "订单",
    "产能",
}

PRODUCT_CAPACITY_TERMS = {
    "product launch",
    "launches",
    "customer qualification",
    "qualified by",
    "capacity expansion",
    "new fab",
    "ramp",
    "expansion",
    "量产",
    "扩产",
}

MAJOR_THEMES = {
    "HBM",
    "HBM4",
    "AI ASIC",
    "AI data center",
    "Robotics",
    "Advanced packaging",
    "EUV",
}

HIGH_FILING_FORMS = {"10-K", "10-Q", "8-K", "S-1", "S-3", "10-K/A", "10-Q/A", "8-K/A"}


def score_item(
    item: ScorableItem,
    *,
    company_name: str = "",
    aliases: Iterable[str] = (),
    is_duplicate: bool = False,
) -> tuple[int, dict[str, int], Materiality]:
    text = _item_text(item)
    source_score = _source_score(item)
    recency_score = _recency_score(item.freshness)
    direct_company_score = _direct_company_score(text, item.ticker, company_name, aliases)
    financial_impact_score = _financial_impact_score(text)
    novelty_score = 8 if not is_duplicate and freshness_label(item.freshness) in {"fresh", "recent"} else 0
    theme_score = _theme_score(getattr(item, "related_themes", []))
    filing_score = _filing_score(item)
    stale_penalty = _stale_penalty(item)
    duplicate_penalty = -20 if is_duplicate else 0
    low_quality_source_penalty = _low_quality_source_penalty(item)
    headline_only_penalty = -10 if getattr(item, "content_depth", "") == "headline_only" else 0

    breakdown = {
        "source_score": source_score,
        "recency_score": recency_score,
        "direct_company_score": direct_company_score,
        "financial_impact_score": financial_impact_score,
        "novelty_score": novelty_score,
        "theme_score": theme_score,
        "filing_score": filing_score,
        "stale_penalty": stale_penalty,
        "duplicate_penalty": duplicate_penalty,
        "low_quality_source_penalty": low_quality_source_penalty,
        "headline_only_penalty": headline_only_penalty,
    }
    score = max(0, min(100, sum(breakdown.values())))
    return score, breakdown, materiality_from_score(score)


def materiality_from_score(score: int) -> Materiality:
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def high_allowed_in_critical(item: ScorableItem) -> bool:
    if freshness_label(item.freshness) != "stale_context":
        return True
    return getattr(item, "item_type", "") in {
        "official_filing",
        "sec_filing",
        "earnings",
        "company_guidance",
        "exchange_announcement",
        "manual_override",
    }


def _source_score(item: ScorableItem) -> int:
    source_name = clean_text(getattr(item, "source_name", "")) or ""
    source = source_name.casefold()
    item_type = getattr(item, "item_type", "")
    aggregator_source = clean_text(getattr(item, "aggregator_source", None)) or ""

    if item_type in {"ir_news", "company_guidance"} or "investor relations" in source:
        return 25
    if item_type in {"sec_filing", "official_filing"} or "sec edgar" in source:
        return 25
    if item_type in {"cn_announcement", "exchange_announcement"} or "announcement" in source:
        return 25
    if any(name in source for name in MAJOR_REPUTABLE_NEWS):
        return 20
    if any(name in source for name in {"semi", "semiconductor", "trendforce", "digitimes"}):
        return 15
    if aggregator_source.casefold() == "google news rss" or "google news" in source:
        return 5
    return 0


def _recency_score(freshness: FreshnessInfo) -> int:
    days = freshness.published_days_ago
    if days is None:
        return 0
    if days <= 3:
        return 20
    if days <= 7:
        return 12
    if days <= 14:
        return 6
    if days <= 30:
        return 2
    return -20


def _direct_company_score(
    text: str, ticker: str, company_name: str, aliases: Iterable[str]
) -> int:
    candidates = [ticker, company_name, *aliases]
    if any(candidate and clean_text(candidate).casefold() in text for candidate in candidates):
        return 15
    if any(term in text for term in {"competitor", "supplier", "customer", "hyperscaler"}):
        return 8
    return 3


def _financial_impact_score(text: str) -> int:
    if any(term in text for term in FINANCIAL_IMPACT_TERMS):
        return 20
    if any(term in text for term in PRODUCT_CAPACITY_TERMS):
        return 15
    if any(term in text for term in {"market commentary", "analyst says", "stock moves"}):
        return 3
    return 0


def _theme_score(themes: list[str]) -> int:
    if any(theme in MAJOR_THEMES for theme in themes):
        return 10
    if themes:
        return 5
    return 0


def _filing_score(item: ScorableItem) -> int:
    form = clean_text(getattr(item, "form", "")) or ""
    form_upper = form.upper()
    if form_upper in HIGH_FILING_FORMS:
        return 25
    if form_upper in {"4", "FORM 4"}:
        return 5
    if form_upper in {"144", "FORM 144"}:
        return 3
    if form_upper.startswith("SC 13") or form_upper.startswith("13"):
        return 10
    if form_upper == "SD":
        return 0
    return 0


def _stale_penalty(item: ScorableItem) -> int:
    days = item.freshness.published_days_ago
    if days is None or days <= 30:
        return 0
    if getattr(item, "item_type", "") in {
        "official_filing",
        "sec_filing",
        "earnings",
        "company_guidance",
        "exchange_announcement",
    }:
        return 0
    return -30


def _low_quality_source_penalty(item: ScorableItem) -> int:
    source = (clean_text(getattr(item, "source_name", "")) or "").casefold()
    canonical_url = clean_text(getattr(item, "canonical_url", None))
    aggregator_url = clean_text(getattr(item, "aggregator_url", None))
    penalty = 0
    if any(name in source for name in {"unknown blog", "blogspot", "substack"}):
        penalty -= 15
    if aggregator_url and not canonical_url:
        penalty -= 5
    if "google news" in source and not canonical_url:
        penalty -= 5
    return penalty


def _item_text(item: ScorableItem) -> str:
    summary = getattr(item, "summary", None)
    if isinstance(summary, SummaryFields):
        summary_text = " ".join(
            [
                summary.what_happened,
                summary.related_theme,
                summary.possible_financial_impact,
                summary.follow_up_needed,
            ]
        )
    else:
        summary_text = str(summary or "")
    return f"{item.title} {summary_text}".casefold()
