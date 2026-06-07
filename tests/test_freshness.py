from datetime import date

from market_agent.freshness import classify_freshness


def test_zero_to_three_days_is_fresh() -> None:
    info = classify_freshness("2026-06-04", date(2026, 6, 7))

    assert info.published_days_ago == 3
    assert info.is_newly_published is True
    assert info.freshness_label == "fresh"


def test_four_to_fourteen_days_is_recent() -> None:
    info = classify_freshness("2026-05-25", date(2026, 6, 7))

    assert info.published_days_ago == 13
    assert info.is_newly_published is True
    assert info.freshness_label == "recent"


def test_fifteen_days_plus_is_stale_context() -> None:
    info = classify_freshness("2026-05-20", date(2026, 6, 7), newly_discovered=True)

    assert info.published_days_ago == 18
    assert info.is_newly_published is False
    assert info.is_newly_discovered is True
    assert info.freshness_label == "stale_context"


def test_missing_published_at_is_unknown() -> None:
    info = classify_freshness(None, date(2026, 6, 7))

    assert info.published_days_ago is None
    assert info.is_newly_published is False
    assert info.freshness_label == "unknown"
