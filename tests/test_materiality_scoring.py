from datetime import date

from market_agent.freshness import classify_freshness
from market_agent.intelligence import classify_filing_materiality, enrich_news_item
from market_agent.models import FilingItem, NewsItem, StockItem
from market_agent.scoring import score_item


def test_earnings_8k_can_score_high_when_content_signals() -> None:
    filing = FilingItem(
        ticker="MU",
        company_name="Micron",
        category="Memory and Storage",
        form="8-K",
        title="8-K earnings guidance update",
        summary="Micron issued earnings guidance update.",
        source_name="SEC EDGAR",
        source_url="https://www.sec.gov/example",
        canonical_url="https://www.sec.gov/example",
        canonical_url_status="resolved",
        published_at="2026-06-02",
        fetched_at="2026-06-03T00:00:00Z",
        freshness=classify_freshness("2026-06-02", date(2026, 6, 3)),
        related_themes=["HBM4"],
    )

    score, breakdown, materiality = score_item(filing, company_name="Micron")

    assert materiality == "high"
    assert score >= 80
    assert breakdown["filing_score"] == 10


def test_critical_sec_forms_default_high() -> None:
    materiality, why, thesis_effect, confidence = classify_filing_materiality("10-Q", "Quarterly report")

    assert materiality == "high"
    assert "core periodic report" in why
    assert thesis_effect == "needs_review"
    assert confidence == "high"


def test_generic_8k_is_not_automatically_high() -> None:
    materiality, why, thesis_effect, confidence = classify_filing_materiality(
        "8-K",
        "Current report",
    )

    assert materiality == "medium"
    assert "not automatically high" in why
    assert thesis_effect == "needs_review"
    assert confidence == "medium"


def test_old_public_news_does_not_become_high() -> None:
    stock = StockItem(ticker="MU", name="Micron", market="US", category="Memory and Storage", themes=["HBM4"])
    item = NewsItem(
        ticker="MU",
        item_type="public_news",
        title="Micron high-bandwidth memory demand accelerates - Unknown Blog",
        summary="title_summary: Micron high-bandwidth memory demand accelerates",
        summary_confidence="low",
        publisher="Unknown Blog",
        source_name="Google News RSS",
        source_url="https://news.google.com/rss/articles/example",
        aggregator_source="Google News RSS",
        aggregator_url="https://news.google.com/rss/articles/example",
        published_at="2026-02-01",
        fetched_at="2026-06-03T00:00:00Z",
    )

    enriched = enrich_news_item(item, stock, ["HBM4"], date(2026, 6, 3))

    assert enriched.freshness.freshness_label == "stale_context"
    assert enriched.materiality != "high"


def test_headline_only_is_penalized() -> None:
    stock = StockItem(ticker="MU", name="Micron", market="US", category="Memory and Storage", themes=["HBM4"])
    headline = NewsItem(
        ticker="MU",
        item_type="public_news",
        title="Micron HBM4 guidance update",
        summary="title_summary: Micron HBM4 guidance update",
        summary_confidence="low",
        source_name="Google News RSS",
        source_url="https://example.com/headline",
        published_at="2026-06-02",
        fetched_at="2026-06-03T00:00:00Z",
    )
    excerpt = headline.model_copy(
        update={
            "summary": "Micron discussed HBM4 demand and guidance in an article excerpt.",
            "summary_confidence": "medium",
            "content_depth": "article_excerpt",
            "source_name": "Reuters",
            "source_url": "https://example.com/full",
            "canonical_url": "https://example.com/full",
            "canonical_url_status": "resolved",
        }
    )

    headline_enriched = enrich_news_item(headline, stock, ["HBM4"], date(2026, 6, 3))
    excerpt_enriched = enrich_news_item(excerpt, stock, ["HBM4"], date(2026, 6, 3))

    assert headline_enriched.score_breakdown["headline_only_penalty"] == -10
    assert excerpt_enriched.materiality_score > headline_enriched.materiality_score


def test_google_rss_only_does_not_score_high() -> None:
    stock = StockItem(ticker="MU", name="Micron", market="US", category="Memory and Storage", themes=["HBM4"])
    item = NewsItem(
        ticker="MU",
        item_type="public_news",
        title="Micron HBM4 demand guidance update",
        summary="title_summary: Micron HBM4 demand guidance update",
        summary_confidence="low",
        source_name="Google News RSS",
        source_url="https://news.google.com/rss/articles/example",
        aggregator_source="Google News RSS",
        aggregator_url="https://news.google.com/rss/articles/example",
        published_at="2026-06-02",
        fetched_at="2026-06-03T00:00:00Z",
    )

    enriched = enrich_news_item(item, stock, ["HBM4"], date(2026, 6, 3))

    assert enriched.materiality != "high"
    assert enriched.confidence != "high"


def test_hbm4_official_fresh_news_scores_high() -> None:
    stock = StockItem(ticker="MU", name="Micron", market="US", category="Memory and Storage", themes=["HBM4"])
    item = NewsItem(
        ticker="MU",
        item_type="ir_news",
        title="Micron issues HBM4 demand and revenue guidance update",
        summary="Micron issued an official update discussing HBM4 demand, revenue guidance, and capacity ramp.",
        summary_confidence="medium",
        content_depth="article_excerpt",
        source_name="Company Investor Relations RSS",
        source_url="https://investors.example.com/news",
        canonical_url="https://investors.example.com/news",
        canonical_url_status="resolved",
        published_at="2026-06-02",
        fetched_at="2026-06-03T00:00:00Z",
    )

    enriched = enrich_news_item(item, stock, ["HBM4"], date(2026, 6, 3))

    assert enriched.materiality == "high"
    assert enriched.materiality_score >= 80
