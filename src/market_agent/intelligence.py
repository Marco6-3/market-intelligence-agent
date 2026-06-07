from __future__ import annotations

import re
from datetime import date
from typing import Iterable

from .deduplication import deduplicate_and_cluster_news
from .freshness import classify_freshness as build_freshness_info
from .freshness import freshness_label
from .models import (
    AnalystReviewQueueItem,
    AnalystTriage,
    AnalystTriageItem,
    CategorySummary,
    Confidence,
    EarningsCalendarItem,
    FilingItem,
    FreshnessInfo,
    IntelligenceItem,
    MarketSnapshot,
    Materiality,
    NewsItem,
    SourceQuality,
    StockItem,
    SummaryFields,
    ThesisEffect,
)
from .scoring import high_allowed_in_critical, score_item
from .theme_aliases import related_themes_and_terms
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

MEDIUM_PUBLISHERS = {
    "cnbc",
    "barron's",
    "barrons",
    "barron’s",
    "yahoo finance",
    "the motley fool",
    "motley fool",
    "seeking alpha",
    "24/7 wall st.",
    "24/7 wall st",
}

DEMAND_TERMS = {
    "ai data center",
    "ai datacenter",
    "hbm",
    "hbm3e",
    "hbm4",
    "demand accelerates",
    "surging demand",
    "strong demand",
    "cloud demand",
    "capex",
}

SUPPORT_TERMS = {
    "price hike",
    "price increase",
    "pricing power",
    "tight supply",
    "shortage",
    "memory shortage",
    "contract price",
    "spot price",
    "asp",
    "qualification",
    "ramp",
}

WEAKEN_TERMS = {
    "capacity expansion",
    "expand capacity",
    "oversupply",
    "shortage eases",
    "competition",
    "competitor",
    "rival",
    "downgrade",
    "export control",
    "sanctions",
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
    themes, _ = related_themes_and_matched_terms(title, summary, terms)
    return themes


def related_themes_and_matched_terms(
    title: object, summary: object, terms: Iterable[str]
) -> tuple[list[str], list[str]]:
    return related_themes_and_terms(
        title,
        summary_to_text(summary),
        extra_terms=terms,
    )


def enrich_news_item(
    item: NewsItem,
    stock: StockItem,
    global_keywords: Iterable[str],
    report_date: date,
) -> NewsItem:
    themes, matched_terms = related_themes_and_matched_terms(
        item.title,
        item.summary,
        theme_terms_for_stock(stock, global_keywords),
    )
    freshness = classify_freshness(item.published_at, report_date)
    source_quality = classify_source_quality(item)
    content_depth = item.content_depth or _content_depth_from_summary(item)
    confidence = _cap_confidence(
        item.confidence,
        content_depth=content_depth,
        aggregator_url=item.aggregator_url,
        canonical_url=item.canonical_url,
    )
    thesis_effect = classify_news_thesis_effect(item, themes)
    summary = _structured_news_summary(
        item=item,
        stock=stock,
        themes=themes,
        content_depth=content_depth,
        confidence=confidence,
    )
    provisional = item.model_copy(
        update={
            "company_name": stock.name,
            "category": stock.category,
            "summary": summary,
            "summary_confidence": summary.evidence_strength,
            "related_themes": themes,
            "matched_terms": matched_terms,
            "freshness": freshness,
            "source_quality": source_quality,
            "content_depth": content_depth,
            "confidence": confidence,
            "thesis_effect": thesis_effect,
            "core_claim": item.core_claim or core_claim_from_title(item.title),
        }
    )
    score, breakdown, materiality = score_item(
        provisional,
        company_name=stock.name,
        aliases=stock.aliases,
        is_duplicate=provisional.is_duplicate,
    )
    why = news_why_it_matters(provisional, themes, materiality)
    return provisional.model_copy(
        update={
            "materiality_score": score,
            "score_breakdown": breakdown,
            "materiality": materiality,
            "why_it_matters": why,
        }
    )


def classify_news_materiality(item: NewsItem, related_themes: list[str]) -> Materiality:
    provisional = item.model_copy(update={"related_themes": related_themes})
    _, _, materiality = score_item(provisional)
    return materiality


def news_why_it_matters(
    item: NewsItem, related_themes: list[str], materiality: Materiality
) -> str:
    label = freshness_label(item.freshness)
    evidence = item.summary.evidence_strength
    if item.content_depth == "headline_only":
        depth_note = "headline only; full article not fetched"
    elif item.content_depth == "article_excerpt":
        depth_note = "article excerpt available"
    else:
        depth_note = "full article available"
    if related_themes:
        return (
            f"Tracked theme(s) matched: {', '.join(related_themes)}; "
            f"score={item.materiality_score}; freshness={label}; evidence={evidence}; {depth_note}."
        )
    if materiality in {"high", "medium"}:
        return (
            f"Company/source signal scored {materiality}; "
            f"freshness={label}; evidence={evidence}; {depth_note}."
        )
    return (
        f"No strong tracked theme or verified impact matched; "
        f"freshness={label}; evidence={evidence}; {depth_note}."
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
            "needs_review",
            "high",
        )
    if form_upper.startswith("S-3"):
        return (
            "high",
            "S-3 registration can affect financing capacity, dilution risk, or capital markets optionality.",
            "needs_review",
            "high",
        )
    if "earnings release" in haystack or "results of operations" in haystack:
        return (
            "high",
            "Filing appears tied to earnings/results disclosure, which is directly relevant to estimates and thesis updates.",
            "needs_review",
            "high",
        )
    if form_upper == "SD":
        if any(term in haystack for term in SUPPLY_CHAIN_RISK_TERMS):
            return (
                "high",
                "Form SD text includes supply-chain or conflict-minerals risk language that may affect sourcing resilience.",
                "needs_review",
                "medium",
            )
        return (
            "low",
            "Form SD is usually compliance-oriented; no major supply-chain risk terms were detected.",
            "neutral",
            "medium",
        )
    if form_upper in {"4", "FORM 4"}:
        level, why = _ownership_filing_materiality(document_text, default="medium")
        return (level, why, "needs_review", "medium")
    if form_upper in {"144", "FORM 144"}:
        level, why = _ownership_filing_materiality(document_text, default="low")
        return (level, why, "needs_review", "medium")
    if form_upper.startswith("SC 13") or form_upper.startswith("SCHEDULE 13"):
        return (
            "medium",
            "Beneficial-ownership filing can signal position changes by large holders.",
            "needs_review",
            "medium",
        )
    return (
        "low",
        "No default high/medium materiality rule matched; keep in appendix unless corroborated.",
        "neutral",
        "low",
    )


def enrich_filing_item(
    filing: FilingItem,
    stock: StockItem,
    global_keywords: Iterable[str],
    report_date: date,
) -> FilingItem:
    themes, matched_terms = related_themes_and_matched_terms(
        filing.title or filing.form,
        filing.summary,
        theme_terms_for_stock(stock, global_keywords),
    )
    freshness = classify_freshness(filing.published_at or filing.filing_date, report_date)
    score, breakdown, materiality = score_item(
        filing.model_copy(
            update={
                "company_name": stock.name,
                "category": stock.category,
                "related_themes": themes,
                "matched_terms": matched_terms,
                "freshness": freshness,
                "source_quality": "high",
                "content_depth": "article_excerpt",
            }
        ),
        company_name=stock.name,
        aliases=stock.aliases,
    )
    materiality = max_materiality(filing.materiality, materiality)
    summary = filing.summary.model_copy(
        update={
            "affected_company": stock.name,
            "related_theme": ", ".join(themes) if themes else "not available",
            "evidence_strength": filing.confidence,
            "follow_up_needed": "Read the official filing and compare changes versus the prior period.",
        }
    )
    return filing.model_copy(
        update={
            "company_name": stock.name,
            "category": stock.category,
            "summary": summary,
            "related_themes": themes,
            "matched_terms": matched_terms,
            "freshness": freshness,
            "content_depth": "article_excerpt",
            "source_quality": "high",
            "materiality_score": score,
            "score_breakdown": breakdown,
            "materiality": materiality,
        }
    )


def market_snapshot_to_item(snapshot: MarketSnapshot, stock: StockItem | None = None) -> IntelligenceItem:
    title = f"{snapshot.ticker} market snapshot"
    summary_text = (
        f"price={_fmt_number(snapshot.price)} {snapshot.currency or ''}; "
        f"change_percent={_fmt_number(snapshot.change_percent)}%; "
        f"previous_close={_fmt_number(snapshot.previous_close)}; "
        f"volume={_fmt_int(snapshot.volume)}"
    )
    materiality: Materiality = "medium" if abs(snapshot.change_percent or 0) >= 3 else "low"
    score = 55 if materiality == "medium" else 30
    return IntelligenceItem(
        ticker=snapshot.ticker,
        company_name=stock.name if stock else snapshot.name or "not available",
        category=stock.category if stock else "Uncategorized",
        item_type="market_snapshot",
        title=title,
        summary=SummaryFields(
            what_happened=summary_text,
            affected_company=stock.name if stock else snapshot.name or snapshot.ticker,
            related_theme="not available",
            possible_financial_impact="Price and volume changes can prioritize follow-up, but yfinance is non-official market data.",
            evidence_strength="medium",
            follow_up_needed="Verify material moves with official filings, earnings releases, or reputable market coverage.",
        ),
        summary_confidence="medium",
        why_it_matters="Price and liquidity movement frame the urgency of follow-up analysis.",
        related_themes=[],
        matched_terms=[],
        materiality=materiality,
        materiality_score=score,
        score_breakdown={"market_move_score": score},
        thesis_effect="needs_review" if materiality == "medium" else "neutral",
        confidence="medium",
        freshness=FreshnessInfo(freshness_label="unknown"),
        content_depth="article_excerpt",
        source_quality="medium",
        source_name=snapshot.source_name,
        source_url=snapshot.source_url,
        final_url=snapshot.final_url,
        canonical_url=snapshot.canonical_url,
        canonical_url_status=snapshot.canonical_url_status,
        aggregator_source=snapshot.aggregator_source,
        aggregator_url=snapshot.aggregator_url,
        published_at=snapshot.published_at,
        fetched_at=snapshot.fetched_at,
    )


def news_to_item(news: NewsItem) -> IntelligenceItem:
    return IntelligenceItem(
        ticker=news.ticker,
        company_name=news.company_name,
        category=news.category,
        item_type=news.item_type,
        title=news.title,
        summary=news.summary,
        summary_confidence=news.summary_confidence,
        why_it_matters=news.why_it_matters or "not available",
        related_themes=news.related_themes,
        matched_terms=news.matched_terms,
        materiality=news.materiality,
        materiality_score=news.materiality_score,
        score_breakdown=news.score_breakdown,
        thesis_effect=news.thesis_effect,
        confidence=news.confidence,
        freshness=news.freshness,
        content_depth=news.content_depth,
        source_quality=news.source_quality,
        cluster_id=news.cluster_id,
        cluster_size=news.cluster_size,
        cluster_sources=news.cluster_sources,
        core_claim=news.core_claim,
        is_duplicate=news.is_duplicate,
        source_name=news.source_name,
        source_url=news.source_url,
        final_url=news.final_url,
        canonical_url=news.canonical_url,
        canonical_url_status=news.canonical_url_status,
        aggregator_source=news.aggregator_source,
        aggregator_url=news.aggregator_url,
        published_at=news.published_at,
        fetched_at=news.fetched_at,
    )


def filing_to_item(filing: FilingItem) -> IntelligenceItem:
    return IntelligenceItem(
        ticker=filing.ticker,
        company_name=filing.company_name,
        category=filing.category,
        item_type="sec_filing",
        title=filing.title or f"{filing.form} filing",
        summary=filing.summary,
        summary_confidence="high" if filing.form.upper() in HIGH_FILING_FORMS else "medium",
        why_it_matters=filing.why_it_matters or "not available",
        related_themes=filing.related_themes,
        matched_terms=filing.matched_terms,
        materiality=filing.materiality,
        materiality_score=filing.materiality_score,
        score_breakdown=filing.score_breakdown,
        thesis_effect=filing.thesis_effect,
        confidence=filing.confidence,
        freshness=filing.freshness,
        content_depth=filing.content_depth,
        source_quality="high",
        core_claim=filing.title or f"{filing.form} filing",
        source_name=filing.source_name,
        source_url=filing.source_url,
        final_url=filing.final_url,
        canonical_url=filing.canonical_url,
        canonical_url_status=filing.canonical_url_status,
        aggregator_source=filing.aggregator_source,
        aggregator_url=filing.aggregator_url,
        published_at=filing.published_at,
        fetched_at=filing.fetched_at,
    )


def earnings_calendar_to_item(
    item: EarningsCalendarItem, stock: StockItem | None = None
) -> IntelligenceItem:
    summary_text = (
        f"report_date={item.report_date or 'not available'}; "
        f"eps_estimate={_fmt_number(item.eps_estimate)}; "
        f"revenue_estimate={_fmt_number(item.revenue_estimate)}"
    )
    return IntelligenceItem(
        ticker=item.ticker,
        company_name=stock.name if stock else "not available",
        category=stock.category if stock else "Uncategorized",
        item_type="earnings",
        title=f"{item.ticker} earnings calendar",
        summary=SummaryFields(
            what_happened=summary_text,
            affected_company=stock.name if stock else item.ticker,
            related_theme="earnings",
            possible_financial_impact="Upcoming earnings can change revenue, margin, guidance, and capex expectations.",
            evidence_strength="medium",
            follow_up_needed="Prepare follow-up questions before the earnings date.",
        ),
        summary_confidence="medium",
        why_it_matters="Upcoming earnings timing sets the next catalyst window.",
        related_themes=[],
        matched_terms=[],
        materiality="medium",
        materiality_score=55,
        score_breakdown={"earnings_calendar_score": 55},
        thesis_effect="needs_review",
        confidence="medium",
        freshness=FreshnessInfo(freshness_label="unknown"),
        content_depth="article_excerpt",
        source_quality="high" if item.source_name in {"Alpha Vantage", "Finnhub"} else "medium",
        core_claim=f"{item.ticker} earnings expected on {item.report_date or 'not available'}",
        source_name=item.source_name,
        source_url=item.source_url,
        final_url=item.final_url,
        canonical_url=item.canonical_url,
        canonical_url_status=item.canonical_url_status,
        aggregator_source=item.aggregator_source,
        aggregator_url=item.aggregator_url,
        published_at=item.published_at,
        fetched_at=item.fetched_at,
    )


def classify_freshness(published_at: str | None, report_date: date) -> FreshnessInfo:
    return build_freshness_info(published_at, report_date)


def classify_source_quality(item: NewsItem) -> SourceQuality:
    source_name = (item.source_name or "").casefold()
    publisher = (item.publisher or "").casefold()
    aggregator_source = (item.aggregator_source or "").casefold()

    if item.item_type in {"ir_news", "cn_announcement"}:
        return "high"
    if any(name in source_name for name in HIGH_SOURCE_NAMES):
        return "high"
    if _matches_publisher(source_name, HIGH_PUBLISHERS) or _matches_publisher(publisher, HIGH_PUBLISHERS):
        return "high"
    if _matches_publisher(source_name, MEDIUM_PUBLISHERS) or _matches_publisher(publisher, MEDIUM_PUBLISHERS):
        return "medium"
    if source_name in {"financial modeling prep", "alpha vantage", "finnhub"}:
        return "medium"
    if item.item_type == "public_news" or "google news" in source_name or "google news" in aggregator_source:
        return "low"
    return "unknown"


def classify_news_thesis_effect(item: NewsItem, related_themes: list[str]) -> ThesisEffect:
    haystack = f"{item.title} {summary_to_text(item.summary)}".casefold()
    if _has_any_term(haystack, WEAKEN_TERMS):
        return "weakens_thesis"
    if _has_any_term(haystack, SUPPORT_TERMS) or _has_any_term(haystack, DEMAND_TERMS):
        return "supports_thesis"
    if related_themes:
        return "needs_review"
    if item.materiality == "low":
        return "neutral"
    return "needs_review"


def cluster_news_items(news: list[NewsItem]) -> list[NewsItem]:
    representatives, _ = deduplicate_and_cluster_news(news)
    return representatives


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
                evidence_strength=_evidence_strength_text(item),
                possible_thesis_effect=item.thesis_effect,
                follow_up_questions=_follow_up_questions(item),
                item_type=item.item_type,
                materiality=item.materiality,
                source_quality=item.source_quality,
                freshness=item.freshness,
                source_url=_display_url(item),
            )
        )
    return queue


def build_analyst_triage(items: Iterable[IntelligenceItem]) -> AnalystTriage:
    material = list(items)
    must = [
        item
        for item in material
        if item.materiality == "high"
        and high_allowed_in_critical(item)
        and (freshness_label(item.freshness) in {"fresh", "recent"} or item.item_type in {"sec_filing", "earnings"})
    ]
    watch = [
        item
        for item in material
        if item.materiality == "medium"
        and freshness_label(item.freshness) in {"fresh", "recent", "unknown"}
        and not item.is_duplicate
    ]
    background = [
        item
        for item in material
        if freshness_label(item.freshness) == "stale_context" and item.materiality in {"medium", "low"}
    ]
    noise = [
        item
        for item in material
        if item.materiality == "low"
        or item.confidence == "low"
        or item.content_depth == "headline_only"
        or item.is_duplicate
    ]
    return AnalystTriage(
        must_review_today=[_triage_item(item, "High score, fresh/official source, and relevant to tracked themes.") for item in _rank_items(must)[:5]],
        watch_items=[_triage_item(item, "Medium materiality or recent signal that needs verification.") for item in _rank_items(watch)[:10]],
        background_context=[_triage_item(item, "Stale or contextual item; useful background but not a critical alert.") for item in _rank_items(background)[:20]],
        noise_duplicate_low_confidence=[_triage_item(item, "Low confidence, headline-only, duplicate, or low materiality.") for item in _rank_items(noise)[:20]],
    )


def build_category_summary(stocks: Iterable[StockItem], items: Iterable[IntelligenceItem]) -> list[CategorySummary]:
    stocks_by_category: dict[str, list[StockItem]] = {}
    for stock in stocks:
        stocks_by_category.setdefault(stock.category or "Uncategorized", []).append(stock)

    result: list[CategorySummary] = []
    material = list(items)
    for category, category_stocks in stocks_by_category.items():
        tickers = {stock.ticker for stock in category_stocks}
        category_items = [item for item in material if item.ticker in tickers or item.category == category]
        key_movers = [
            f"{item.ticker}: {item.summary.what_happened}"
            for item in category_items
            if item.item_type == "market_snapshot" and item.materiality in {"high", "medium"}
        ][:5]
        important_news = [
            f"{item.ticker}: {item.title}"
            for item in _rank_items(category_items)
            if item.item_type != "market_snapshot" and item.materiality in {"high", "medium"}
        ][:5]
        themes = _unique(theme for item in category_items for theme in item.related_themes)
        evidence = "high" if any(item.confidence == "high" for item in category_items) else "medium" if category_items else "low"
        result.append(
            CategorySummary(
                category=category,
                key_movers=key_movers,
                important_news=important_news,
                demand_signal=", ".join(themes[:5]) if themes else "not available",
                risk_signal=_category_risk_signal(category_items),
                evidence_strength=evidence,  # type: ignore[arg-type]
            )
        )
    return result


def core_claim_from_title(title: str) -> str:
    claim = re.sub(r"\s+-\s+[^-]{2,80}$", "", title).strip()
    claim = re.sub(r"\s+", " ", claim)
    return claim or title


def summary_to_text(summary: object) -> str:
    if isinstance(summary, SummaryFields):
        return " ".join(
            [
                summary.what_happened,
                summary.affected_company,
                summary.related_theme,
                summary.possible_financial_impact,
                summary.follow_up_needed,
            ]
        )
    return clean_text(summary) or ""


def _structured_news_summary(
    *,
    item: NewsItem,
    stock: StockItem,
    themes: list[str],
    content_depth: str,
    confidence: Confidence,
) -> SummaryFields:
    raw_text = summary_to_text(item.summary)
    if content_depth == "headline_only":
        what_happened = f"headline only; full article not fetched: {item.title}"
        evidence_strength: Confidence = "low"
        follow_up = "Fetch or verify the original article before using this claim."
    else:
        if raw_text and not _summary_repeats_title(raw_text, item.title):
            what_happened = raw_text
        else:
            what_happened = f"Article excerpt is thin; verify original article: {item.title}"
        evidence_strength = confidence
        follow_up = "Verify details against the canonical article or official source."
    return SummaryFields(
        what_happened=truncate(what_happened, 700) or "not available",
        affected_company=stock.name,
        related_theme=", ".join(themes) if themes else "not available",
        possible_financial_impact=_possible_financial_impact(item.title, raw_text, themes),
        evidence_strength=evidence_strength,
        follow_up_needed=follow_up,
    )


def _possible_financial_impact(title: str, summary: str, themes: list[str]) -> str:
    haystack = f"{title} {summary}".casefold()
    if any(term in haystack for term in ["earnings", "guidance", "revenue", "margin", "profit", "业绩"]):
        return "May affect revenue, margin, guidance, or estimate assumptions; verify from primary source."
    if any(term in haystack for term in ["capex", "demand", "supply", "pricing", "price", "shortage"]):
        return "May affect demand, supply, pricing, or capex assumptions; quantify with official data if possible."
    if themes:
        return "Theme-relevant signal; financial impact is not available until corroborated by primary data."
    return "not available"


def _content_depth_from_summary(item: NewsItem) -> str:
    text = summary_to_text(item.summary)
    if not text or item.summary_confidence == "low" or text.casefold().startswith("title_summary:"):
        return "headline_only"
    return "article_excerpt"


def _cap_confidence(
    confidence: Confidence,
    *,
    content_depth: str,
    aggregator_url: str | None,
    canonical_url: str | None,
) -> Confidence:
    if content_depth == "headline_only":
        return "low" if confidence == "high" else confidence
    if aggregator_url and not canonical_url and confidence == "high":
        return "medium"
    return confidence


def _summary_repeats_title(summary: str, title: str) -> bool:
    normalized_summary = _normalize_for_compare(summary)
    normalized_title = _normalize_for_compare(title)
    return bool(normalized_title and normalized_summary.startswith(normalized_title))


def _normalize_for_compare(value: object) -> str:
    text = clean_text(value) or ""
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text.casefold())
    return re.sub(r"\s+", " ", text).strip()


def _triage_item(item: IntelligenceItem, reason: str) -> AnalystTriageItem:
    return AnalystTriageItem(
        ticker=item.ticker,
        title=item.title,
        reason=reason,
        follow_up_needed=item.summary.follow_up_needed,
        materiality=item.materiality,
        materiality_score=item.materiality_score,
        freshness_label=freshness_label(item.freshness),
        evidence_strength=item.summary.evidence_strength,
        source_url=_display_url(item),
    )


def _rank_items(items: Iterable[IntelligenceItem]) -> list[IntelligenceItem]:
    return sorted(
        items,
        key=lambda item: (
            -item.materiality_score,
            {"high": 0, "medium": 1, "low": 2}.get(item.materiality, 9),
            item.ticker,
            item.title,
        ),
    )


def _review_queue_score(item: IntelligenceItem) -> int:
    score = 0
    if item.materiality == "high":
        score += 40
    elif item.materiality == "medium":
        score += 20
    if item.item_type in {"public_news", "ir_news", "cn_announcement"} and item.cluster_size > 1:
        score += 15
    if item.summary_confidence == "low":
        score += 10
    if item.source_quality in {"low", "unknown"} and item.materiality in {"high", "medium"}:
        score += 10
    if item.thesis_effect != "neutral":
        score += 10
    if item.item_type in {"sec_filing", "earnings"} and item.materiality in {"high", "medium"}:
        score += 10
    return score


def _evidence_strength_text(item: IntelligenceItem) -> str:
    if item.source_quality == "high" and item.summary.evidence_strength in {"high", "medium"}:
        return "strong"
    if item.cluster_size >= 2 and item.source_quality in {"high", "medium"}:
        return "moderate"
    if item.summary.evidence_strength == "low" or item.source_quality in {"low", "unknown"}:
        return "weak"
    return "moderate"


def _follow_up_questions(item: IntelligenceItem) -> list[str]:
    questions = [
        "What primary source or full article text confirms the core claim?",
        "Does the claim change demand, pricing, supply, competition, capex, or valuation assumptions?",
    ]
    if item.content_depth == "headline_only":
        questions.append("Can the headline-only item be replaced with article text or a reliable snippet?")
    if item.cluster_size > 1:
        questions.append("Do clustered sources report the same fact, or repeat one syndicated story?")
    if item.item_type == "earnings":
        questions.append("What questions should be prepared before the earnings date?")
    return questions[:4]


def _category_risk_signal(items: list[IntelligenceItem]) -> str:
    risk_items = [item for item in items if item.thesis_effect in {"weakens_thesis", "needs_review"}]
    if not risk_items:
        return "not available"
    return "; ".join(f"{item.ticker}: {item.title}" for item in _rank_items(risk_items)[:3])


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


def _display_url(item: IntelligenceItem) -> str:
    return item.canonical_url or item.final_url or item.source_url


def _unique(values: Iterable[str | None]) -> list[str]:
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


def _fmt_number(value: float | None) -> str:
    return "not available" if value is None else f"{value:.2f}"


def _fmt_int(value: int | None) -> str:
    return "not available" if value is None else f"{value:,}"


def max_materiality(first: Materiality, second: Materiality) -> Materiality:
    rank = {"high": 0, "medium": 1, "low": 2}
    return first if rank[first] <= rank[second] else second


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
