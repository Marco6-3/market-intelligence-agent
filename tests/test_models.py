from pydantic import ValidationError

from market_agent.config import AppConfig
from market_agent.models import NewsItem, Watchlist


def test_watchlist_validates_stock_market_case() -> None:
    watchlist = Watchlist.model_validate(
        {
            "timezone": "Asia/Singapore",
            "keywords": ["HBM"],
            "stocks": [
                {
                    "ticker": "MU",
                    "name": "Micron",
                    "market": "us",
                    "aliases": ["Micron Technology"],
                    "themes": ["DRAM"],
                }
            ],
        }
    )

    assert watchlist.stocks[0].market == "US"


def test_watchlist_rejects_empty_stocks() -> None:
    try:
        Watchlist.model_validate({"stocks": []})
    except ValidationError as exc:
        assert "stocks" in str(exc)
    else:
        raise AssertionError("Expected ValidationError")


def test_source_fields_are_required_on_news() -> None:
    item = NewsItem(
        ticker="MU",
        title="Micron headline",
        summary=None,
        publisher="Example",
        symbols=["MU"],
        source_name="Example Source",
        source_url="https://example.com/story",
        published_at="2026-06-01",
        fetched_at="2026-06-01T00:00:00Z",
    )

    dumped = item.model_dump()
    assert dumped["source_url"] == "https://example.com/story"
    assert dumped["source_name"] == "Example Source"
    assert dumped["published_at"] == "2026-06-01"
    assert dumped["fetched_at"] == "2026-06-01T00:00:00Z"


def test_config_reads_kimi_llm_settings(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "YFINANCE_ENABLED=true",
                "LLM_PROVIDER=moonshot",
                "LLM_BASE_URL=https://api.moonshot.cn/anthropic",
                "LLM_MODEL=kimi-k2.6",
                "LLM_API_KEY=test-key",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    config = AppConfig.from_env(env_file)

    assert config.yfinance_enabled is True
    assert config.llm_provider == "moonshot"
    assert config.llm_model == "kimi-k2.6"
    assert config.llm_api_key == "test-key"
