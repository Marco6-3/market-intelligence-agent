from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from typing import Iterable

from .models import (
    AnalystReviewQueueItem,
    Confidence,
    EarningsCalendarItem,
    FilingItem,
    Freshness,
    IntelligenceItem,
    MarketSnapshot,
    Materiality,
    NewsClusterSource,
    NewsItem,
    SourceQuality,
    StockItem,
    ThesisEffect,
)
from .utils.text import clean_text, truncate

DEFAULT_THEME_KEYWORDS = [
    "HBM",
    "HBM3E",
    "HBM4",
    "DRAM price",
    "NAND price",
    "AI data center",
    "enterprise SSD",
    "nearline HDD",
    "memory shortage",
    "memory oversupply",
]

HIGH_NEWS_THEMES = {
    "hbm3e",
    "hbm4",
    "dram price",
    "nand price",
    "memory shortage",
    "memory oversupply",
}

HIGH_FILING_FORMS = {
    "10-K",
    "10-K/A",
    "10-Q",
    "10-Q/A",
    "8-K",
    "8-K/A",
    "20-F",
    "20-F/A",
    "6-K",
    "6-K/A",
}

SUPPLY_CHAIN_RISK_TERMS = [
    "material supply chain risk",
    "supply chain disruption",
    "supply chain constraint",
    "forced labor",
    "sanctions",
    "export control",
    "unable to determine",
    "material adverse",
    "供应链风险",
    "供应中断",
]

HIGH_SOURCE_NAMES = {
    "company_ir",
    "company investor relations rss",
    "sec edgar",
    "exchange_filings",
    "earnings_call",
    "akshare cn announcements",
}

HIGH_PUBLISHERS = {
    "reuters",
    "bloomberg",
    "the wall street journal",
    "wall street journal",
    "wsj",
    "nikkei",
    "financial times",
    "ft",
}

MEDIUM_HIGH_PUBLISHERS = {
    "cnbc",
    "barron's",
    "barrons",
    "barron’s",
}

MEDIUM_PUBLISHERS = {
    "yahoo finance",
    "the motley fool",
    "motley fool",
    "seeking alpha",
    "24/7 wall st.",
    "24/7 wall st",
}

MAJOR_DISCLOSURE_TERMS = {
    "10-k",
    "10-q",
    "8-k",
    "earnings",
    "financial results",
    "quarterly results",
    "annual results",
    "guidance",
    "preliminary results",
    "profit warning",
    "major announcement",
    "重大公告",
    "财报",
    "业绩",
    "季度报告",
    "年度报告",
}

DEMAND_THESIS_TERMS = {
    "ai data center",
    "ai datacenter",
    "hbm",
    "hbm3e",
    "hbm4",
    "demand accelerates",
    "surging demand",
    "strong demand",
    "cloud demand",
}

PRICING_POWER_TERMS = {
    "price hike",
    "price increase",
    "pricing power",
    "tight supply",
    "shortage",
    "memory shortage",
    "contract price",
    "spot price",
    "asp",
}

SUPPLY_EXPANSION_TERMS = {
    "double wafer capacity",
    "capacity expansion",
    "expand capacity",
    "new fab",
    "supply increase",
    "oversupply",
    "shortage eases",
}

COMPETITION_RISK_TERMS = {
    "market share",
    "samsung",
    "sk hynix",
    "kioxia",
    "competition",
    "competitor",
    "threat",
    "rival",
}

VALUATION_RISK_TERMS = {
    "valuation",
    "downgrade",
    "price target",
    "stock is up",
    "rally",
    "sell",
    "multiple",
    "overvalued",
}

CLUSTER_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "for",
    "from",
    "in",
    "is",
    "its",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "amid",
    "says",
    "said",
    "stock",
    "stocks",
    "update",
}


def theme_terms_for_stock(stock: StockItem, global_keywords: Iterable[str]) -> list[str]:
    terms = [*DEFAULT_THEME_KEYWORDS, *global_keywords, *stock.themes, *stock.aliases, stock.name]
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        cleaned = clean_text(term)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def related_themes_for_text(title: object, summary: object, terms: Iterable[str]) -> list[str]:
    haystack = f"{title or ''} {summary or ''}".casefold()
    matches: list[str] = []
    seen: set[str] = set()
    for term in terms:
        cleaned = clean_text(term)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen or key not in haystack:
            continue
        seen.add(key)
        matches.append(cleaned)
    return matches


def enrich_news_item(
    item: NewsItem,
    stock: StockItem,
    global_keywords: Iterable[str],
    report_date: date,
) -> NewsItem:
    themes = related_themes_for_text(
        item.title,
        item.summary,
        theme_terms_for_stock(stock, global_keywords),
    )
    freshness = classify_freshness(item.published_at, report_date)
    source_quality = classify_source_quality(item)
    thesis_effect = classify_news_thesis_effect(item, themes)
    item_for_scoring = item.model_copy(
        update={
            "related_themes": themes,
            "freshness": freshness,
            "source_quality": source_quality,
            "thesis_effect": thesis_effect,
        }
    )
    materiality = _max_materiality(
        item.materiality,
        classify_news_materiality(item_for_scoring, themes),
    )
    materiality = _cap_news_materiality(item_for_scoring, themes, materiality)
    why_it_matters = news_why_it_matters(item_for_scoring, themes, materiality)
    if item.why_it_matters != "not available" and not themes:
        why_it_matters = item.why_it_matters
    return item_for_scoring.model_copy(
        update={
            "related_themes": themes,
            "materiality": materiality,
            "why_it_matters": why_it_matters,
            "confidence": "medium" if themes else item.confidence,
            "freshness": freshness,
            "source_quality": source_quality,
            "thesis_effect": thesis_effect,
            "core_claim": item.core_claim or core_claim_from_title(item.title),
        }
    )


def classify_news_materiality(item: NewsItem, related_themes: list[str]) -> Materiality:
    title_summary = f"{item.title} {item.summary or ''}".casefold()
    high_signal = any(theme.casefold() in HIGH_NEWS_THEMES for theme in related_themes)
    high_signal = high_signal or re.search(
        r"\b(earnings|guidance|preliminary results|financial results)\b",
        title_summary,
    ) is not None
    high_signal = high_signal or _has_any_term(title_summary, MAJOR_DISCLOSURE_TERMS)

    if high_signal:
        materiality: Materiality = "high"
    elif related_themes:
        materiality = "medium"
    elif item.item_type in {"ir_news", "cn_announcement"} or item.source_quality == "high":
        materiality = "medium"
    else:
        materiality = "low"

    if materiality == "high" and item.freshness in {"stale", "background"} and not _allows_stale_high(item):
        materiality = "medium" if related_themes and item.source_quality in {"high", "medium"} else "low"

    if materiality == "high" and item.source_quality == "medium" and item.freshness not in {"fresh", "recent"}:
        materiality = "medium"
    if materiality == "high" and item.source_quality in {"low", "unknown"}:
        materiality = "medium" if item.freshness in {"fresh", "recent"} and related_themes else "low"

    return materiality


def _cap_news_materiality(
    item: NewsItem,
    related_themes: list[str],
    materiality: Materiality,
) -> Materiality:
    if materiality != "high":
        return materiality
    if item.freshness in {"stale", "background"} and not _allows_stale_high(item):
        return "medium" if related_themes and item.source_quality in {"high", "medium"} else "low"
    if item.source_quality == "medium" and item.freshness not in {"fresh", "recent"}:
        return "medium"
    if item.source_quality in {"low", "unknown"}:
        return "medium" if item.freshness in {"fresh", "recent"} and related_themes else "low"
    return materiality


def news_why_it_matters(
    item: NewsItem, related_themes: list[str], materiality: Materiality
) -> str:
    freshness_note = f"freshness={item.freshness}; source_quality={item.source_quality}."
    if related_themes:
        return (
            "Mentions tracked theme(s): "
            f"{', '.join(related_themes)}; {freshness_note} "
            "Review for impact on the investment thesis."
        )
    if materiality == "high":
        return (
            "Company-level financial or guidance language appears in the headline/summary; "
            f"{freshness_note}"
        )
    if item.item_type == "ir_news":
        return (
            "Company Investor Relations release; source is primary but no tracked theme matched. "
            f"{freshness_note}"
        )
    return (
        "No tracked theme matched in the collected title/summary; treat as background until verified. "
        f"{freshness_note}"
    )


def classify_filing_materiality(
    form: object, description: object = None, document_text: str | None = None
) -> tuple[Materiality, str, ThesisEffect, Confidence]:
    form_upper = clean_text(form).upper() if clean_text(form) else "UNKNOWN"
    description_text = clean_text(description) or ""
    haystack = f"{form_upper} {description_text} {truncate(document_text, 3000) or ''}".casefold()

    if form_upper in HIGH_FILING_FORMS:
        return (
            "high",
            f"{form_upper} is a core periodic/current report and can contain material operating, risk, or guidance updates.",
            "needs_manual_review",
            "high",
        )
    if form_upper.startswith("S-3"):
        return (
            "high",
            "S-3 registration can affect financing capacity, dilution risk, or capital markets optionality.",
            "valuation_risk",
            "high",
        )
    if "earnings release" in haystack or "results of operations" in haystack:
        return (
            "high",
            "Filing appears tied to earnings/results disclosure, which is directly relevant to estimates and thesis updates.",
            "needs_manual_review",
            "high",
        )
    if form_upper == "SD":
        if any(term in haystack for term in SUPPLY_CHAIN_RISK_TERMS):
            return (
                "high",
                "Form SD text includes supply-chain or conflict-minerals risk language that may affect sourcing resilience.",
                "needs_manual_review",
                "medium",
            )
        return (
            "low",
            "Form SD is usually compliance-oriented; no major supply-chain risk terms were detected.",
            "background_only",
            "medium",
        )
    if form_upper in {"4", "FORM 4"}:
        level, why = _ownership_filing_materiality(document_text, default="medium")
        return (level, why, "needs_manual_review", "medium")
    if form_upper in {"144", "FORM 144"}:
        level, why = _ownership_filing_materiality(document_text, default="low")
        return (level, why, "needs_manual_review", "medium")
    if form_upper.startswith("SC 13") or form_upper.startswith("SCHEDULE 13"):
        return (
            "medium",
            "Beneficial-ownership filing can signal position changes by large holders.",
            "needs_manual_review",
            "medium",
        )
    return (
        "low",
        "No default high/medium materiality rule matched; keep in appendix unless corroborated.",
        "background_only",
        "low",
    )


def market_snapshot_to_item(snapshot: MarketSnapshot) -> IntelligenceItem:
    title = f"{snapshot.ticker} market snapshot"
    summary = (
        f"price={_fmt_number(snapshot.price)} {snapshot.currency or ''}; "
        f"change_percent={_fmt_number(snapshot.change_percent)}%; "
        f"previous_close={_fmt_number(snapshot.previous_close)}; "
        f"volume={_fmt_int(snapshot.volume)}"
    )
    materiality: Materiality = "medium" if abs(snapshot.change_percent or 0) >= 3 else "low"
    thesis_effect: ThesisEffect = "valuation_risk" if materiality == "medium" else "background_only"
    return IntelligenceItem(
        ticker=snapshot.ticker,
        item_type="market_snapshot",
        title=title,
        summary=summary,
        summary_confidence="medium",
        why_it_matters="Price and liquidity movement frame the urgency of follow-up analysis.",
        related_themes=[],
        materiality=materiality,
        thesis_effect=thesis_effect,
        confidence="medium",
        source_name=snapshot.source_name,
        source_url=snapshot.source_url,
        final_url=snapshot.final_url,
        aggregator_url=snapshot.aggregator_url,
        published_at=snapshot.published_at,
        fetched_at=snapshot.fetched_at,
    )


def news_to_item(news: NewsItem) -> IntelligenceItem:
    return IntelligenceItem(
        ticker=news.ticker,
        item_type=news.item_type,
        title=news.title,
        summary=news.summary or "not available",
        summary_confidence=news.summary_confidence,
        why_it_matters=news.why_it_matters or "not available",
        related_themes=news.related_themes,
        materiality=news.materiality,
        thesis_effect=news.thesis_effect,
        confidence=news.confidence,
        freshness=news.freshness,
        source_quality=news.source_quality,
        cluster_id=news.cluster_id,
        cluster_size=news.cluster_size,
        cluster_sources=news.cluster_sources,
        core_claim=news.core_claim,
        source_name=news.source_name,
        source_url=news.source_url,
        final_url=news.final_url,
        aggregator_url=news.aggregator_url,
        published_at=news.published_at,
        fetched_at=news.fetched_at,
    )


def filing_to_item(filing: FilingItem) -> IntelligenceItem:
    return IntelligenceItem(
        ticker=filing.ticker,
        item_type="sec_filing",
        title=filing.title or f"{filing.form} filing",
        summary=filing.summary or filing.description or "not available",
        summary_confidence="high" if filing.form.upper() in HIGH_FILING_FORMS else "medium",
        why_it_matters=filing.why_it_matters or "not available",
        related_themes=[],
        materiality=filing.materiality,
        thesis_effect=filing.thesis_effect,
        confidence=filing.confidence,
        source_quality="high",
        core_claim=filing.title or f"{filing.form} filing",
        source_name=filing.source_name,
        source_url=filing.source_url,
        final_url=filing.final_url,
        aggregator_url=filing.aggregator_url,
        published_at=filing.published_at,
        fetched_at=filing.fetched_at,
    )


def earnings_calendar_to_item(item: EarningsCalendarItem) -> IntelligenceItem:
    summary = (
        f"report_date={item.report_date or 'not available'}; "
        f"eps_estimate={_fmt_number(item.eps_estimate)}; "
        f"revenue_estimate={_fmt_number(item.revenue_estimate)}"
    )
    return IntelligenceItem(
        ticker=item.ticker,
        item_type="earnings_calendar",
        title=f"{item.ticker} earnings calendar",
        summary=summary,
        summary_confidence="high",
        why_it_matters="Upcoming earnings timing sets the next catalyst window.",
        related_themes=[],
        materiality="medium",
        thesis_effect="needs_manual_review",
        confidence="medium",
        source_quality="high" if item.source_name in {"Alpha Vantage", "Finnhub"} else "medium",
        core_claim=f"{item.ticker} earnings expected on {item.report_date or 'not available'}",
        source_name=item.source_name,
        source_url=item.source_url,
        final_url=item.final_url,
        aggregator_url=item.aggregator_url,
        published_at=item.published_at,
        fetched_at=item.fetched_at,
    )


def classify_freshness(published_at: str | None, report_date: date) -> Freshness:
    published_date = _parse_date(published_at)
    if published_date is None:
        return "unknown"
    age_days = (report_date - published_date).days
    if age_days <= 7:
        return "fresh"
    if age_days <= 30:
        return "recent"
    if age_days <= 90:
        return "stale"
    return "background"


def classify_source_quality(item: NewsItem) -> SourceQuality:
    source_name = (item.source_name or "").casefold()
    publisher = (item.publisher or "").casefold()

    if item.item_type in {"ir_news", "cn_announcement"}:
        return "high"
    if any(name in source_name for name in HIGH_SOURCE_NAMES):
        return "high"
    if _matches_publisher(publisher, HIGH_PUBLISHERS):
        return "high"
    if _matches_publisher(publisher, MEDIUM_HIGH_PUBLISHERS | MEDIUM_PUBLISHERS):
        return "medium"
    if source_name in {"financial modeling prep", "alpha vantage", "finnhub"}:
        return "medium"
    if item.item_type == "public_news" or "google news" in source_name:
        return "low"
    return "unknown"


def classify_news_thesis_effect(item: NewsItem, related_themes: list[str]) -> ThesisEffect:
    haystack = f"{item.title} {item.summary or ''}".casefold()
    if _has_any_term(haystack, SUPPLY_EXPANSION_TERMS):
        return "weakens_supply_shortage_thesis"
    if _has_any_term(haystack, COMPETITION_RISK_TERMS):
        return "increases_competition_risk"
    if _has_any_term(haystack, VALUATION_RISK_TERMS):
        return "valuation_risk"
    if _has_any_term(haystack, PRICING_POWER_TERMS):
        return "supports_pricing_power"
    if _has_any_term(haystack, DEMAND_THESIS_TERMS) or any(
        theme.casefold() in {"hbm", "hbm3e", "hbm4", "ai memory", "ai storage"}
        for theme in related_themes
    ):
        return "supports_demand_thesis"
    if not related_themes or item.materiality == "low":
        return "background_only"
    return "needs_manual_review"


def cluster_news_items(news: list[NewsItem]) -> list[NewsItem]:
    clusters: list[list[NewsItem]] = []
    cluster_tokens: list[set[str]] = []

    for item in news:
        tokens = _cluster_tokens(item.title)
        matched_index: int | None = None
        for index, existing_tokens in enumerate(cluster_tokens):
            if item.ticker.upper() != clusters[index][0].ticker.upper():
                continue
            if _token_similarity(tokens, existing_tokens) >= 0.62:
                matched_index = index
                break
        if matched_index is None:
            clusters.append([item])
            cluster_tokens.append(tokens)
        else:
            clusters[matched_index].append(item)
            cluster_tokens[matched_index] |= tokens

    return [_news_cluster_representative(cluster) for cluster in clusters]


def build_analyst_review_queue(
    items: Iterable[IntelligenceItem], limit: int = 5
) -> list[AnalystReviewQueueItem]:
    candidates = [item for item in items if _review_queue_score(item) > 0]
    candidates.sort(key=lambda item: (-_review_queue_score(item), item.ticker, item.title))
    queue: list[AnalystReviewQueueItem] = []
    for item in candidates[:limit]:
        queue.append(
            AnalystReviewQueueItem(
                ticker=item.ticker,
                core_claim=item.core_claim or item.title,
                why_it_matters=item.why_it_matters,
                evidence_strength=_evidence_strength(item),
                possible_thesis_effect=item.thesis_effect,
                follow_up_questions=_follow_up_questions(item),
                item_type=item.item_type,
                materiality=item.materiality,
                source_quality=item.source_quality,
                freshness=item.freshness,
                source_url=item.final_url or item.source_url,
            )
        )
    return queue


def core_claim_from_title(title: str) -> str:
    claim = re.sub(r"\s+-\s+[^-]{2,80}$", "", title).strip()
    claim = re.sub(r"\s+", " ", claim)
    return claim or title


def _news_cluster_representative(items: list[NewsItem]) -> NewsItem:
    lead = sorted(items, key=_news_lead_sort_key)[0]
    cluster_sources = [_cluster_source_ref(item) for item in items]
    cluster_id = _cluster_id(lead.ticker, lead.core_claim or core_claim_from_title(lead.title))
    related_themes = _unique_preserving_order(
        theme for item in items for theme in item.related_themes
    )
    materiality = _cluster_materiality(items, related_themes)
    source_quality = _best_source_quality(item.source_quality for item in items)
    freshness = _best_freshness(item.freshness for item in items)
    summary, summary_confidence = _cluster_summary(lead, len(items))
    why = lead.why_it_matters
    if len(items) > 1:
        source_names = _unique_preserving_order(
            (item.publisher or item.source_name) for item in items
        )
        why = (
            f"{why} Clustered from {len(items)} similar item(s): "
            f"{', '.join(source_names[:5])}; materiality is scored at cluster level."
        )

    return lead.model_copy(
        update={
            "summary": summary,
            "summary_confidence": summary_confidence,
            "why_it_matters": why,
            "related_themes": related_themes,
            "materiality": materiality,
            "thesis_effect": _cluster_thesis_effect(items),
            "confidence": _cluster_confidence(items, summary_confidence),
            "freshness": freshness,
            "source_quality": source_quality,
            "cluster_id": cluster_id,
            "cluster_size": len(items),
            "cluster_sources": cluster_sources,
            "core_claim": lead.core_claim or core_claim_from_title(lead.title),
        }
    )


def _cluster_source_ref(item: NewsItem) -> NewsClusterSource:
    return NewsClusterSource(
        source_name=item.source_name,
        publisher=item.publisher,
        source_url=item.source_url,
        final_url=item.final_url,
        aggregator_url=item.aggregator_url,
        source_quality=item.source_quality,
        freshness=item.freshness,
        published_at=item.published_at,
    )


def _news_lead_sort_key(item: NewsItem) -> tuple[int, int, int, int, str]:
    return (
        _source_quality_rank(item.source_quality),
        _freshness_rank(item.freshness),
        _materiality_rank(item.materiality),
        -_date_ordinal(item.published_at),
        item.title,
    )


def _cluster_materiality(items: list[NewsItem], related_themes: list[str]) -> Materiality:
    materiality = _best_materiality(item.materiality for item in items)
    source_quality = _best_source_quality(item.source_quality for item in items)
    freshness = _best_freshness(item.freshness for item in items)
    has_high_theme = any(theme.casefold() in HIGH_NEWS_THEMES for theme in related_themes)
    has_major = any(_allows_stale_high(item) for item in items)

    if (
        materiality == "medium"
        and len(items) >= 2
        and source_quality in {"high", "medium"}
        and freshness in {"fresh", "recent"}
        and has_high_theme
    ):
        materiality = "high"

    if materiality == "high" and freshness in {"stale", "background"} and not has_major:
        materiality = "medium" if source_quality in {"high", "medium"} and related_themes else "low"
    if materiality == "high" and source_quality in {"low", "unknown"}:
        materiality = "medium" if freshness in {"fresh", "recent"} and related_themes else "low"
    return materiality


def _cluster_thesis_effect(items: list[NewsItem]) -> ThesisEffect:
    for label in [
        "weakens_supply_shortage_thesis",
        "increases_competition_risk",
        "valuation_risk",
        "supports_pricing_power",
        "supports_demand_thesis",
        "needs_manual_review",
    ]:
        if any(item.thesis_effect == label for item in items):
            return label  # type: ignore[return-value]
    return "background_only"


def _cluster_confidence(items: list[NewsItem], summary_confidence: Confidence) -> Confidence:
    if any(item.source_quality == "high" for item in items) and summary_confidence != "low":
        return "high"
    if len(items) >= 2 and any(item.source_quality in {"high", "medium"} for item in items):
        return "medium"
    if all(item.source_quality == "low" for item in items):
        return "low"
    return "medium"


def _cluster_summary(lead: NewsItem, cluster_size: int) -> tuple[str, Confidence]:
    core_claim = lead.core_claim or core_claim_from_title(lead.title)
    if cluster_size == 1:
        return lead.summary or f"title_summary: {core_claim}", lead.summary_confidence
    if lead.summary and lead.summary_confidence != "low":
        return (
            f"{lead.summary} Clustered with {cluster_size - 1} similar source(s); "
            "verify full articles before using non-headline details.",
            lead.summary_confidence,
        )
    return (
        f"title_summary: {core_claim}. Clustered from {cluster_size} similar headlines; "
        "no full article text was confirmed.",
        "low",
    )


def _review_queue_score(item: IntelligenceItem) -> int:
    score = 0
    if item.materiality == "high":
        score += 40
    elif item.materiality == "medium":
        score += 20
    if item.item_type in {"public_news", "news", "ir_news", "cn_announcement"} and item.cluster_size > 1:
        score += 15
    if item.summary_confidence == "low":
        score += 10
    if item.source_quality in {"low", "unknown"} and item.materiality in {"high", "medium"}:
        score += 10
    if item.thesis_effect != "background_only":
        score += 10
    if item.item_type in {"sec_filing", "earnings_calendar"} and item.materiality in {"high", "medium"}:
        score += 10
    return score


def _evidence_strength(item: IntelligenceItem) -> str:
    if item.source_quality == "high" and item.summary_confidence in {"high", "medium"}:
        return "strong"
    if item.cluster_size >= 2 and item.source_quality in {"high", "medium"}:
        return "moderate"
    if item.summary_confidence == "low" or item.source_quality in {"low", "unknown"}:
        return "weak"
    return "moderate"


def _follow_up_questions(item: IntelligenceItem) -> list[str]:
    questions = [
        "What primary source or full article text confirms the core claim?",
        "Does the claim change demand, pricing, supply, competition, or valuation assumptions?",
    ]
    if item.summary_confidence == "low":
        questions.append("Can the title-only summary be replaced with article text or a reliable snippet?")
    if item.cluster_size > 1:
        questions.append("Do the clustered sources report the same fact, or are they repeating one syndicated story?")
    if item.item_type == "earnings_calendar":
        questions.append("What questions should be prepared before the earnings date?")
    return questions[:4]


def _allows_stale_high(item: NewsItem) -> bool:
    haystack = f"{item.title} {item.summary or ''}".casefold()
    return item.manually_marked or _has_any_term(haystack, MAJOR_DISCLOSURE_TERMS)


def _has_any_term(text: str, terms: Iterable[str]) -> bool:
    lowered = text.casefold()
    return any(term.casefold() in lowered for term in terms)


def _matches_publisher(publisher: str, candidates: set[str]) -> bool:
    if not publisher:
        return False
    normalized = publisher.replace("’", "'").casefold()
    for candidate in candidates:
        candidate_normalized = candidate.replace("’", "'").casefold()
        if normalized == candidate_normalized or candidate_normalized in normalized:
            return True
    return False


def _cluster_tokens(title: str) -> set[str]:
    claim = core_claim_from_title(title).casefold()
    tokens = set(re.findall(r"[a-z0-9]+", claim))
    return {token for token in tokens if len(token) > 1 and token not in CLUSTER_STOPWORDS}


def _token_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    union = len(left | right)
    containment = overlap / min(len(left), len(right))
    jaccard = overlap / union
    return max(jaccard, containment * 0.85)


def _cluster_id(ticker: str, core_claim: str) -> str:
    digest = hashlib.sha1(f"{ticker.upper()}|{core_claim.casefold()}".encode("utf-8")).hexdigest()
    return f"{ticker.upper()}-{digest[:10]}"


def _unique_preserving_order(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = clean_text(value)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _best_materiality(values: Iterable[Materiality]) -> Materiality:
    return min(values, key=_materiality_rank)


def _best_source_quality(values: Iterable[SourceQuality]) -> SourceQuality:
    return min(values, key=_source_quality_rank)


def _best_freshness(values: Iterable[Freshness]) -> Freshness:
    return min(values, key=_freshness_rank)


def _materiality_rank(value: Materiality) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(value, 9)


def _source_quality_rank(value: SourceQuality) -> int:
    return {"high": 0, "medium": 1, "low": 2, "unknown": 3}.get(value, 9)


def _freshness_rank(value: Freshness) -> int:
    return {"fresh": 0, "recent": 1, "stale": 2, "background": 3, "unknown": 4}.get(value, 9)


def _date_ordinal(value: str | None) -> int:
    parsed = _parse_date(value)
    return parsed.toordinal() if parsed else 0


def _parse_date(value: str | None) -> date | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed.date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _ownership_filing_materiality(
    document_text: str | None, default: Materiality
) -> tuple[Materiality, str]:
    amount, shares = _extract_ownership_transaction_size(document_text)
    if amount is not None and amount >= 10_000_000:
        return (
            "high",
            f"Ownership filing appears to involve a transaction value of about ${amount:,.0f}, above the high-signal threshold.",
        )
    if shares is not None and shares >= 1_000_000:
        return (
            "high",
            f"Ownership filing appears to involve about {shares:,.0f} shares, above the high-signal threshold.",
        )
    if amount is not None and amount >= 1_000_000:
        return (
            "medium",
            f"Ownership filing appears to involve a transaction value of about ${amount:,.0f}.",
        )
    if shares is not None and shares >= 100_000:
        return (
            "medium",
            f"Ownership filing appears to involve about {shares:,.0f} shares.",
        )
    if default == "medium":
        return (
            "medium",
            "Form 4 insider ownership filing; no unusually large transaction size was detected from the primary document.",
        )
    return (
        "low",
        "Form 144 resale notice; no unusually large transaction size was detected from the primary document.",
    )


def _extract_ownership_transaction_size(document_text: str | None) -> tuple[float | None, float | None]:
    if not document_text:
        return None, None
    shares = _max_tag_value(document_text, "transactionShares") or _max_tag_value(
        document_text, "securitiesToBeSold"
    )
    prices = _values_for_wrapped_tag(document_text, "transactionPricePerShare")
    share_values = _values_for_wrapped_tag(document_text, "transactionShares")
    amounts = _values_for_names(document_text, ["transactionTotalValue", "aggregateMarketValue"])
    if prices and share_values:
        amounts.extend(share * price for share, price in zip(share_values, prices))
    return (max(amounts) if amounts else None, shares)


def _max_tag_value(text: str, tag_name: str) -> float | None:
    values = _values_for_wrapped_tag(text, tag_name)
    return max(values) if values else None


def _values_for_wrapped_tag(text: str, tag_name: str) -> list[float]:
    pattern = rf"<{tag_name}\b[^>]*>.*?<value>([\d,]+(?:\.\d+)?)</value>.*?</{tag_name}>"
    return [_parse_number(value) for value in re.findall(pattern, text, flags=re.I | re.S)]


def _values_for_names(text: str, names: Iterable[str]) -> list[float]:
    values: list[float] = []
    for name in names:
        pattern = rf"<{name}\b[^>]*>\s*<?value>?([\d,]+(?:\.\d+)?)"
        values.extend(_parse_number(value) for value in re.findall(pattern, text, flags=re.I))
    return [value for value in values if value is not None]


def _parse_number(value: str) -> float:
    return float(value.replace(",", ""))


def _fmt_number(value: float | None) -> str:
    return "not available" if value is None else f"{value:.2f}"


def _fmt_int(value: int | None) -> str:
    return "not available" if value is None else f"{value:,}"


def _max_materiality(first: Materiality, second: Materiality) -> Materiality:
    rank = {"high": 0, "medium": 1, "low": 2}
    return first if rank[first] <= rank[second] else second
