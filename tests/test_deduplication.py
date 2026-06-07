from market_agent.deduplication import deduplicate_and_cluster_news, exact_dedupe_news
from market_agent.models import NewsItem


def _news(title: str, url: str, canonical_url: str | None = None) -> NewsItem:
    return NewsItem(
        ticker="MU",
        title=title,
        summary="Micron HBM update.",
        summary_confidence="medium",
        content_depth="article_excerpt",
        source_name="Reuters",
        source_url=url,
        canonical_url=canonical_url or url,
        canonical_url_status="resolved",
        published_at="2026-06-02",
        fetched_at="2026-06-03T00:00:00Z",
    )


def test_same_canonical_url_dedupes() -> None:
    items = [
        _news("Micron HBM4 demand rises", "https://example.com/a", "https://example.com/story"),
        _news("Micron HBM4 demand rises", "https://example.com/b", "https://example.com/story"),
    ]

    deduped = exact_dedupe_news(items)

    assert len(deduped) == 1


def test_similar_titles_cluster() -> None:
    items = [
        _news("Micron HBM4 demand rises as AI data center capex grows", "https://example.com/a"),
        _news("Micron HBM4 demand rises amid AI datacenter capex growth", "https://example.com/b"),
    ]

    representatives, clusters = deduplicate_and_cluster_news(items)

    assert len(representatives) == 1
    assert len(clusters) == 1
    assert clusters[0].source_count == 2


def test_same_event_multiple_sources_merge_into_cluster() -> None:
    items = [
        _news("Micron expands HBM4 capacity for AI demand", "https://example.com/reuters"),
        _news("Micron expands HBM4 capacity as AI demand grows", "https://example.com/cnbc"),
    ]

    representatives, clusters = deduplicate_and_cluster_news(items)

    assert representatives[0].cluster_size == 2
    assert clusters[0].primary_title
    assert clusters[0].items[0]["source_url"]
