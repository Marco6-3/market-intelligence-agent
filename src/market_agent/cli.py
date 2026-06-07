from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .config import AppConfig
from .pipeline import load_watchlist, run_daily_brief

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
    typer.echo(
        f"Watchlist valid: {len(parsed.stocks)} stocks, "
        f"{len(parsed.keywords)} keywords, timezone={parsed.timezone}"
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
