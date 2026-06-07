from pathlib import Path

from pydantic import ValidationError
from typer.testing import CliRunner

from market_agent.config import AppConfig
from market_agent.models import Watchlist
from market_agent.pipeline import load_watchlist, select_watchlist_stocks
from market_agent.cli import app
from market_agent.scope import A_SHARE_OUT_OF_SCOPE_MESSAGE, out_of_scope_warnings


runner = CliRunner()


def test_watchlist_supports_legacy_stocks() -> None:
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
    assert select_watchlist_stocks(watchlist, "daily")[0].ticker == "MU"


def test_watchlist_supports_daily_and_weekly_scopes() -> None:
    watchlist = Watchlist.model_validate(
        {
            "daily_core_stocks": [
                {"ticker": "NVDA", "name": "Nvidia", "market": "US", "category": "AI Compute"}
            ],
            "weekly_extended_stocks": [
                {"ticker": "ANET", "name": "Arista", "market": "US", "category": "AI ASIC and Networking"}
            ],
        }
    )

    assert [stock.ticker for stock in select_watchlist_stocks(watchlist, "daily")] == ["NVDA"]
    assert [stock.ticker for stock in select_watchlist_stocks(watchlist, "weekly")] == ["NVDA", "ANET"]
    assert [stock.ticker for stock in select_watchlist_stocks(watchlist, "all")] == ["NVDA", "ANET"]


def test_example_watchlist_without_cn_stocks_validates_successfully() -> None:
    watchlist = load_watchlist(Path(__file__).parents[1] / "watchlist.example.yaml")

    assert len(select_watchlist_stocks(watchlist, "daily")) == 22
    assert out_of_scope_warnings(select_watchlist_stocks(watchlist, "all")) == []


def test_validate_watchlist_warns_for_a_share_without_crashing(tmp_path) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text(
        "\n".join(
            [
                "daily_core_stocks:",
                "  - ticker: 688008.SH",
                "    name: Montage Technology",
                "    market: CN",
                "    category: Memory and Storage",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["validate-watchlist", "--watchlist", str(path)])

    assert result.exit_code == 0
    assert "Watchlist valid" in result.output
    assert A_SHARE_OUT_OF_SCOPE_MESSAGE in result.output


def test_watchlist_rejects_empty_stock_lists() -> None:
    try:
        Watchlist.model_validate({"stocks": []})
    except ValidationError as exc:
        assert "watchlist must define" in str(exc)
    else:
        raise AssertionError("Expected ValidationError")


def test_config_reads_llm_settings(tmp_path, monkeypatch) -> None:
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
