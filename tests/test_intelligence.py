from datetime import date

from market_agent.intelligence import (
    cluster_news_items,
    enrich_news_item,
    classify_filing_materiality,
)
from market_agent.models import NewsItem, StockItem


def test_critical_sec_forms_default_high() -> None:
    materiality, why, thesis_effect, confidence = classify_filing_materiality("10-Q", "Quarterly report")

    assert materiality == "high"
    assert "core periodic/current report" in why
    assert thesis_effect == "needs_manual_review"
    assert confidence == "high"


def test_form_144_defaults_low_without_large_transaction() -> None:
    materiality, why, _, confidence = classify_filing_materiality("144", None, "<xml />")

    assert materiality == "low"
    assert "Form 144 resale notice" in why
    assert confidence == "medium"


def test_form_4_large_transaction_upgrades_high() -> None:
    document = """
    <transactionShares><value>2000000</value></transactionShares>
    <transactionPricePerShare><value>12.50</value></transactionPricePerShare>
    """

    materiality, why, _, _ = classify_filing_materiality("4", None, document)

    assert materiality == "high"
    assert "$25,000,000" in why


def test_stale_public_news_cannot_default_to_high_materiality() -> None:
    stock = StockItem(ticker="MU", name="Micron", market="US", themes=["HBM4"])
    item = NewsItem(
        ticker="MU",
        item_type="public_news",
        title="Micron HBM4 demand accelerates - Unknown Blog",
        summary="title_summary: Micron HBM4 demand accelerates",
        summary_confidence="low",
        materiality="high",
        publisher="Unknown Blog",
        source_name="Google News RSS",
        source_url="https://example.com/story",
        published_at="2026-02-01",
        fetched_at="2026-06-03T00:00:00Z",
    )

    enriched = enrich_news_item(item, stock, ["HBM4"], date(2026, 6, 3))

    assert enriched.freshness == "background"
    assert enriched.source_quality == "low"
    assert enriched.materiality != "high"


def test_similar_news_clusters_and_scores_at_cluster_level() -> None:
    stock = StockItem(ticker="MU", name="Micron", market="US", themes=["AI memory"])
    base = {
        "ticker": "MU",
        "item_type": "public_news",
        "summary_confidence": "low",
        "source_name": "Google News RSS",
        "published_at": "2026-06-02",
        "fetched_at": "2026-06-03T00:00:00Z",
    }
    first = NewsItem(
        **base,
        title="SK Hynix to double wafer capacity amid AI memory shortage - Reuters",
        summary="title_summary: SK Hynix to double wafer capacity amid AI memory shortage",
        publisher="Reuters",
        source_url="https://example.com/reuters",
    )
    second = NewsItem(
        **base,
        title="SK Hynix Vows To Double Wafer Capacity To Combat AI Memory Shortage - CNBC",
        summary="title_summary: SK Hynix Vows To Double Wafer Capacity To Combat AI Memory Shortage",
        publisher="CNBC",
        source_url="https://example.com/cnbc",
    )

    enriched = [
        enrich_news_item(first, stock, ["memory shortage"], date(2026, 6, 3)),
        enrich_news_item(second, stock, ["memory shortage"], date(2026, 6, 3)),
    ]
    clustered = cluster_news_items(enriched)

    assert len(clustered) == 1
    assert clustered[0].cluster_size == 2
    assert len(clustered[0].cluster_sources) == 2
    assert clustered[0].materiality == "high"
    assert clustered[0].thesis_effect == "weakens_supply_shortage_thesis"
