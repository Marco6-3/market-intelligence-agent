from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Iterable

from .freshness import freshness_label, parse_date
from .models import NewsCluster, NewsClusterSource, NewsItem
from .utils.text import clean_text


STOPWORDS = {
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


def deduplicate_and_cluster_news(news: list[NewsItem]) -> tuple[list[NewsItem], list[NewsCluster]]:
    exact = exact_dedupe_news(news)
    clusters = _cluster_news(exact)
    representatives = [_representative(cluster) for cluster in clusters]
    return representatives, [news_cluster_from_items(cluster) for cluster in clusters]


def exact_dedupe_news(news: Iterable[NewsItem]) -> list[NewsItem]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[NewsItem] = []
    for item in news:
        canonical = item.canonical_url or item.final_url or item.source_url
        key = (
            item.ticker.upper(),
            _normalize_title(item.title),
            canonical.casefold(),
            (item.published_at or "")[:10],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def news_cluster_from_items(items: list[NewsItem]) -> NewsCluster:
    lead = _lead_item(items)
    cluster_id = lead.cluster_id or _cluster_id(lead.ticker, lead.core_claim or lead.title)
    related_themes = _unique(theme for item in items for theme in item.related_themes)
    return NewsCluster(
        cluster_id=cluster_id,
        primary_title=lead.title,
        tickers=_unique(item.ticker for item in items),
        related_themes=related_themes,
        source_count=len({(item.source_name, item.source_url) for item in items}),
        best_source=lead.source_name,
        newest_published_at=_newest_published_at(items),
        items=[
            {
                "ticker": item.ticker,
                "title": item.title,
                "source_name": item.source_name,
                "source_url": item.source_url,
                "canonical_url": item.canonical_url,
                "aggregator_url": item.aggregator_url,
                "published_at": item.published_at,
                "content_depth": item.content_depth,
                "confidence": item.confidence,
            }
            for item in items
        ],
    )


def _cluster_news(news: list[NewsItem]) -> list[list[NewsItem]]:
    clusters: list[list[NewsItem]] = []
    for item in news:
        matched_index: int | None = None
        for index, cluster in enumerate(clusters):
            if item.ticker.upper() != cluster[0].ticker.upper():
                continue
            if _same_event(item, cluster[0]):
                matched_index = index
                break
        if matched_index is None:
            clusters.append([item])
        else:
            clusters[matched_index].append(item)
    return clusters


def _representative(items: list[NewsItem]) -> NewsItem:
    lead = _lead_item(items)
    cluster_id = _cluster_id(lead.ticker, lead.core_claim or lead.title)
    cluster_sources = [_cluster_source(item) for item in items]
    related_themes = _unique(theme for item in items for theme in item.related_themes)
    matched_terms = _unique(term for item in items for term in item.matched_terms)
    source_count = len({(item.source_name, item.source_url) for item in items})
    if source_count > 1:
        follow_up = lead.summary.follow_up_needed
        if "clustered" not in follow_up.casefold():
            follow_up = f"{follow_up} Review cluster sources for same-event duplication."
        summary = lead.summary.model_copy(update={"follow_up_needed": follow_up})
    else:
        summary = lead.summary
    return lead.model_copy(
        update={
            "cluster_id": cluster_id,
            "cluster_size": len(items),
            "cluster_sources": cluster_sources,
            "related_themes": related_themes,
            "matched_terms": matched_terms,
            "summary": summary,
        }
    )


def _lead_item(items: list[NewsItem]) -> NewsItem:
    return sorted(items, key=_lead_sort_key)[0]


def _lead_sort_key(item: NewsItem) -> tuple[int, int, int, int, str]:
    return (
        -item.materiality_score,
        _source_quality_rank(item.source_quality),
        _freshness_rank(freshness_label(item.freshness)),
        -_date_ordinal(item.published_at),
        item.title,
    )


def _cluster_source(item: NewsItem) -> NewsClusterSource:
    return NewsClusterSource(
        source_name=item.source_name,
        publisher=item.publisher,
        source_url=item.source_url,
        final_url=item.final_url,
        canonical_url=item.canonical_url,
        aggregator_source=item.aggregator_source,
        aggregator_url=item.aggregator_url,
        source_quality=item.source_quality,
        freshness=item.freshness,
        published_at=item.published_at,
    )


def _same_event(left: NewsItem, right: NewsItem) -> bool:
    if left.canonical_url and right.canonical_url and left.canonical_url == right.canonical_url:
        return True
    left_title = _normalize_title(left.title)
    right_title = _normalize_title(right.title)
    if left_title == right_title:
        return True
    token_score = _token_similarity(_title_tokens(left.title), _title_tokens(right.title))
    string_score = SequenceMatcher(None, left_title, right_title).ratio()
    return max(token_score, string_score) >= 0.72


def _normalize_title(title: str) -> str:
    text = clean_text(title) or ""
    text = re.sub(r"\s+-\s+[^-]{2,80}$", "", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text.casefold())
    return re.sub(r"\s+", " ", text).strip()


def _title_tokens(title: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", _normalize_title(title)))
    return {token for token in tokens if len(token) > 1 and token not in STOPWORDS}


def _token_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    union = len(left | right)
    containment = overlap / min(len(left), len(right))
    jaccard = overlap / union
    return max(jaccard, containment * 0.85)


def _cluster_id(ticker: str, title: str) -> str:
    digest = hashlib.sha1(f"{ticker.upper()}|{_normalize_title(title)}".encode("utf-8")).hexdigest()
    return f"{ticker.upper()}-{digest[:10]}"


def _newest_published_at(items: list[NewsItem]) -> str | None:
    dated = [item.published_at for item in items if item.published_at]
    return max(dated) if dated else None


def _date_ordinal(value: str | None) -> int:
    parsed = parse_date(value)
    return parsed.toordinal() if parsed else 0


def _source_quality_rank(value: str) -> int:
    return {"high": 0, "medium": 1, "low": 2, "unknown": 3}.get(value, 9)


def _freshness_rank(value: str) -> int:
    return {"fresh": 0, "recent": 1, "stale_context": 2, "unknown": 3}.get(value, 9)


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
