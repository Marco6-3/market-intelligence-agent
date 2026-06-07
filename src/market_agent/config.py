from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _clean_env(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


@dataclass(frozen=True)
class AppConfig:
    fmp_api_key: str | None
    alpha_vantage_api_key: str | None
    finnhub_api_key: str | None
    tushare_token: str | None
    yfinance_enabled: bool
    llm_provider: str
    llm_base_url: str | None
    llm_model: str
    llm_api_key: str | None
    sec_user_agent: str
    cache_ttl_seconds: int

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "AppConfig":
        if env_file and env_file.exists():
            load_dotenv(dotenv_path=env_file, override=False)
        else:
            load_dotenv(override=False)

        ttl_raw = _clean_env(os.getenv("CACHE_TTL_SECONDS"))
        try:
            ttl = int(ttl_raw) if ttl_raw else 6 * 60 * 60
        except ValueError:
            ttl = 6 * 60 * 60

        return cls(
            fmp_api_key=_clean_env(os.getenv("FMP_API_KEY")),
            alpha_vantage_api_key=_clean_env(os.getenv("ALPHA_VANTAGE_API_KEY")),
            finnhub_api_key=_clean_env(os.getenv("FINNHUB_API_KEY")),
            tushare_token=_clean_env(os.getenv("TUSHARE_TOKEN")),
            yfinance_enabled=_parse_bool(os.getenv("YFINANCE_ENABLED"), default=True),
            llm_provider=_clean_env(os.getenv("LLM_PROVIDER")) or "moonshot",
            llm_base_url=(
                _clean_env(os.getenv("LLM_BASE_URL"))
                or _clean_env(os.getenv("ANTHROPIC_BASE_URL"))
                or "https://api.moonshot.cn/anthropic"
            ),
            llm_model=(
                _clean_env(os.getenv("LLM_MODEL"))
                or _clean_env(os.getenv("ANTHROPIC_MODEL"))
                or "kimi-k2.6"
            ),
            llm_api_key=(
                _clean_env(os.getenv("LLM_API_KEY"))
                or _clean_env(os.getenv("ANTHROPIC_AUTH_TOKEN"))
            ),
            sec_user_agent=(
                _clean_env(os.getenv("SEC_USER_AGENT"))
                or "market-intelligence-agent/0.1 contact@example.com"
            ),
            cache_ttl_seconds=max(ttl, 0),
        )


def _parse_bool(value: str | None, default: bool) -> bool:
    cleaned = _clean_env(value)
    if cleaned is None:
        return default
    return cleaned.lower() in {"1", "true", "yes", "y", "on"}
