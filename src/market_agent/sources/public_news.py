from __future__ import annotations

from email.utils import parsedate_to_datetime
from html import unescape
import re
from typing import Callable
from urllib.parse import parse_qs, quote_plus, urlparse
from xml.etree import ElementTree as ET

from ..cache import FileCache
from ..models import NewsItem, StockItem
from ..utils.text import clean_text, truncate
from ..utils.time import coerce_datetime_string, utc_now_iso

GOOGLE_NEWS_SOURCE = "Google News RSS"
IR_SOURCE = "Company Investor Relations RSS"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"

DEFAULT_IR_RSS_URLS = {
    "MU": ["https://investors.micron.com/news-releases/rss"],
    "WDC": ["https://investor.wdc.com/news-releases/rss"],
}


class PublicNewsClient:
    def __init__(self, cache: FileCache) -> None:
        self.cache = cache

    def fetch_company_news(
        self, stock: StockItem, theme_terms: list[str], limit: int = 10
    ) -> list[NewsItem]:
        query = _google_news_query(stock, theme_terms)
        text = self.cache.get_text(
            GOOGLE_NEWS_SOURCE,
            GOOGLE_NEWS_RSS_URL,
            params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
        )
        return _items_from_feed(
            text=text,
            ticker=stock.ticker,
            source_name=GOOGLE_NEWS_SOURCE,
            default_url=f"{GOOGLE_NEWS_RSS_URL}?q={quote_plus(query)}",
            item_type="public_news",
            limit=limit,
            url_resolver=self._resolve_google_news_url,
        )

    def fetch_ir_news(self, stock: StockItem, limit: int = 10) -> list[NewsItem]:
        urls = [*stock.ir_news_urls, *DEFAULT_IR_RSS_URLS.get(stock.ticker.upper(), [])]
        items: list[NewsItem] = []
        seen_urls: set[str] = set()
        for url in urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            text = self.cache.get_text(IR_SOURCE, url)
            items.extend(
                _items_from_feed(
                    text=text,
                    ticker=stock.ticker,
                    source_name=IR_SOURCE,
                    default_url=url,
                    item_type="ir_news",
                    limit=limit,
                    url_resolver=None,
                )
            )
        return _dedupe_news(items)[:limit]

    def _resolve_google_news_url(self, url: str) -> str | None:
        return _resolve_google_news_url(self.cache, url)


def _google_news_query(stock: StockItem, theme_terms: list[str]) -> str:
    company_terms = [stock.ticker, stock.name, *stock.aliases[:2]]
    company_query = " OR ".join(f'"{term}"' for term in company_terms if clean_text(term))
    theme_query = " OR ".join(f'"{term}"' for term in theme_terms[:12] if clean_text(term))
    if theme_query:
        return f"({company_query}) ({theme_query})"
    return company_query


def _items_from_feed(
    text: str,
    ticker: str,
    source_name: str,
    default_url: str,
    item_type: str,
    limit: int,
    url_resolver: Callable[[str], str | None] | None,
) -> list[NewsItem]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    fetched_at = utc_now_iso()
    if _local_name(root.tag) == "feed":
        rows = _atom_entries(root)
    else:
        rows = _rss_items(root)

    items: list[NewsItem] = []
    for row in rows[:limit]:
        title = truncate(row.get("title"), 280)
        if not title:
            continue
        raw_url = row.get("link") or default_url
        final_url, aggregator_url, canonical_url, canonical_status = _final_and_aggregator_urls(
            raw_url, url_resolver
        )
        summary, summary_confidence = _summary_from_feed_row(
            title=title,
            raw_summary=row.get("summary"),
            publisher=row.get("publisher"),
            item_type=item_type,
        )
        publisher = truncate(row.get("publisher"), 120)
        item_source_name = publisher if item_type == "public_news" and publisher else source_name
        content_depth = "headline_only" if summary_confidence == "low" else "article_excerpt"
        items.append(
            NewsItem(
                ticker=ticker,
                item_type=item_type,
                title=title,
                summary=summary,
                summary_confidence=summary_confidence,
                content_depth=content_depth,
                publisher=publisher,
                symbols=[ticker],
                source_name=item_source_name,
                source_url=final_url,
                final_url=final_url,
                canonical_url=canonical_url,
                canonical_url_status=canonical_status,
                aggregator_source=source_name if aggregator_url else None,
                aggregator_url=aggregator_url,
                published_at=_coerce_feed_datetime(row.get("published_at")),
                fetched_at=fetched_at,
            )
        )
    return _dedupe_news(items)


def _rss_items(root: ET.Element) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    for item in root.findall(".//item"):
        rows.append(
            {
                "title": _find_text(item, "title"),
                "summary": _find_text(item, "description"),
                "link": _find_text(item, "link"),
                "published_at": _find_text(item, "pubDate") or _find_text(item, "published"),
                "publisher": _find_text(item, "source"),
            }
        )
    return rows


def _atom_entries(root: ET.Element) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    for entry in root.findall(".//{*}entry"):
        rows.append(
            {
                "title": _find_text(entry, "title"),
                "summary": _find_text(entry, "summary") or _find_text(entry, "content"),
                "link": _atom_link(entry),
                "published_at": _find_text(entry, "published") or _find_text(entry, "updated"),
                "publisher": _find_text(root, "title"),
            }
        )
    return rows


def _find_text(element: ET.Element, name: str) -> str | None:
    direct = element.find(name)
    if direct is None:
        direct = element.find(f"{{*}}{name}")
    if direct is None or direct.text is None:
        return None
    return clean_text(unescape(direct.text))


def _atom_link(entry: ET.Element) -> str | None:
    for link in entry.findall("{*}link"):
        href = link.attrib.get("href")
        if href:
            return href
    return None


def _final_and_aggregator_urls(
    raw_url: str,
    url_resolver: Callable[[str], str | None] | None,
) -> tuple[str, str | None, str | None, str]:
    if not _is_google_news_url(raw_url):
        return raw_url, None, raw_url, "resolved"

    aggregator_url = raw_url
    parsed_target = _target_from_google_query(raw_url)
    if parsed_target:
        return parsed_target, aggregator_url, parsed_target, "resolved"
    if url_resolver:
        resolved = url_resolver(raw_url)
        if resolved and not _is_google_news_url(resolved):
            return resolved, aggregator_url, resolved, "resolved"
    return raw_url, aggregator_url, None, "unavailable"


def _summary_from_feed_row(
    title: str,
    raw_summary: object,
    publisher: object,
    item_type: str,
) -> tuple[str, str]:
    summary = truncate(_strip_html(raw_summary), 700)
    publisher_text = clean_text(publisher)
    title_text = clean_text(title) or ""

    if not summary or _summary_repeats_title(summary, title_text, publisher_text):
        return f"title_summary: {title_text}", "low"

    if item_type == "public_news" and len(summary.split()) <= len(title_text.split()) + 4:
        return f"title_summary: {title_text}", "low"

    return _one_or_two_sentence_summary(summary), "medium"


def _summary_repeats_title(summary: str, title: str, publisher: str | None) -> bool:
    normalized_summary = _normalize_for_compare(summary)
    normalized_title = _normalize_for_compare(title)
    if normalized_summary == normalized_title:
        return True
    if publisher:
        normalized_with_publisher = _normalize_for_compare(f"{title} {publisher}")
        if normalized_summary == normalized_with_publisher:
            return True
    return normalized_title and normalized_summary.startswith(normalized_title)


def _one_or_two_sentence_summary(summary: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", summary)
    sentences = [part.strip() for part in parts if part.strip()]
    if len(sentences) >= 2:
        return truncate(" ".join(sentences[:2]), 700) or summary
    return summary


def _normalize_for_compare(value: object) -> str:
    text = clean_text(value) or ""
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text.casefold())
    return re.sub(r"\s+", " ", text).strip()


def _is_google_news_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.netloc.casefold().endswith("news.google.com")


def _target_from_google_query(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    query = parse_qs(parsed.query)
    for key in ("url", "q"):
        values = query.get(key)
        if values and values[0].startswith(("http://", "https://")):
            return values[0]
    return None


def _resolve_google_news_url(cache: FileCache, url: str) -> str | None:
    return cache.resolve_final_url(
        GOOGLE_NEWS_SOURCE,
        url,
        headers={
            "User-Agent": "market-intelligence-agent/0.1 (+https://news.google.com/rss)",
        },
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _strip_html(value: object) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    return clean_text(re.sub(r"<[^>]+>", " ", unescape(text)))


def _coerce_feed_datetime(value: object) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            return parsed.isoformat()
        return parsed.replace(microsecond=0).isoformat()
    except (TypeError, ValueError):
        return coerce_datetime_string(text)


def _dedupe_news(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[tuple[str, str]] = set()
    deduped: list[NewsItem] = []
    for item in items:
        key = (item.title.casefold(), item.source_url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
