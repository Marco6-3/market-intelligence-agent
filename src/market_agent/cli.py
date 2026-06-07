from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .config import AppConfig
from .pipeline import load_watchlist, run_daily_brief, select_watchlist_stocks

app = typer.Typer(
    help=(
        "Collect market intelligence for a YAML watchlist and export Markdown, "
        "JSON, and source CSV reports."
    )
)


@app.command("validate-watchlist")
def validate_watchlist_command(
    watchlist: Path = typer.Option(
        ...,
        "--watchlist",
        "-w",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to watchlist.yaml.",
    )
) -> None:
    parsed = load_watchlist(watchlist)
    daily_count = len(select_watchlist_stocks(parsed, "daily"))
    weekly_count = len(select_watchlist_stocks(parsed, "weekly"))
    all_count = len(select_watchlist_stocks(parsed, "all"))
    typer.echo(
        f"Watchlist valid: daily={daily_count}, weekly={weekly_count}, all={all_count}, "
        f"keywords={len(parsed.keywords)}, timezone={parsed.timezone}"
    )


@app.command("run")
def run_command(
    watchlist: Path = typer.Option(
        ...,
        "--watchlist",
        "-w",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to watchlist.yaml.",
    ),
    run_date: Optional[str] = typer.Option(
        None,
        "--date",
        help="Report date in YYYY-MM-DD format. Defaults to today in watchlist timezone.",
    ),
    scope: str = typer.Option(
        "daily",
        "--scope",
        help="Watchlist scope: daily, weekly, or all.",
    ),
    max_news_per_ticker: Optional[int] = typer.Option(
        None,
        "--max-news-per-ticker",
        min=1,
        help="Override report_policy.max_news_per_ticker for this run.",
    ),
    output_dir: Path = typer.Option(
        Path("reports"),
        "--output-dir",
        help="Directory for generated report files.",
    ),
    cache_dir: Path = typer.Option(
        Path("data_cache"),
        "--cache-dir",
        help="Directory for API response cache files.",
    ),
) -> None:
    result = run_daily_brief(
        watchlist_path=watchlist,
        run_date=run_date,
        scope=_normalize_scope(scope),
        max_news_per_ticker=max_news_per_ticker,
        output_dir=output_dir,
        cache_dir=cache_dir,
    )
    typer.echo(f"Markdown report: {result.markdown_path}")
    typer.echo(f"JSON report:     {result.json_path}")
    typer.echo(f"Sources CSV:     {result.sources_csv_path}")
    if result.warnings:
        typer.echo("")
        typer.echo("Warnings:")
        for warning in result.warnings:
            typer.echo(f"- {warning}")


@app.command("show-config")
def show_config_command(
    env_file: Path = typer.Option(
        Path(".env"),
        "--env-file",
        help="Path to .env file.",
    )
) -> None:
    config = AppConfig.from_env(env_file)
    typer.echo(f"yfinance_enabled: {config.yfinance_enabled}")
    typer.echo(f"llm_provider: {config.llm_provider}")
    typer.echo(f"llm_model: {config.llm_model}")
    typer.echo(f"llm_base_url: {config.llm_base_url or 'not configured'}")
    typer.echo(f"llm_api_key_configured: {bool(config.llm_api_key)}")


def main() -> None:
    app()


def _normalize_scope(value: str) -> str:
    cleaned = value.strip().lower()
    if cleaned not in {"daily", "weekly", "all"}:
        raise typer.BadParameter("scope must be one of: daily, weekly, all")
    return cleaned
