"""CashTracker CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from cashtracker.categorizer import PromptFn, categorize_transactions
from cashtracker.config import load_config, save_learned_keywords, write_default_config
from cashtracker.models import ParsedStatement, Transaction
from cashtracker.output import write_csv, write_csv_stdout
from cashtracker.parsers.registry import detect_and_parse
from cashtracker.readers.csv_reader import read_csv
from cashtracker.readers.pdf_reader import ScannedPDFError, read_pdf


@click.group()
@click.version_option(package_name="cashtracker")
def main() -> None:
    """CashTracker — Local bank statement parser and categorizer."""


@main.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None, help="Output CSV path")
@click.option("--config", "-c", type=click.Path(path_type=Path), default=None, help="Categories config file")
@click.option("--model", "-m", type=str, default=None, help="Ollama model name")
@click.option("--no-ai", is_flag=True, default=False, help="Skip Ollama, use keyword rules only")
@click.option("--interactive", "-i", is_flag=True, default=False, help="Interactively confirm/assign categories")
@click.option("--debug-headers", is_flag=True, default=False, help="Print extracted column headers and exit (no data shown)")
def parse(
    file: Path,
    output: Path | None,
    config: Path | None,
    model: str | None,
    no_ai: bool,
    interactive: bool,
    debug_headers: bool,
) -> None:
    """Parse a bank statement and categorize transactions."""
    cfg = load_config(config)
    config_path = Path(config) if config else Path("categories.yaml")
    if model:
        cfg.ollama.model = model

    # Read raw data
    raw_data = _read_file(file)

    if debug_headers:
        if raw_data:
            click.echo(f"Extracted {len(raw_data)} rows")
            click.echo(f"Column headers: {list(raw_data[0].keys())}")
        else:
            click.echo("No data extracted from file.")
        return

    # Parse into transactions
    statement = detect_and_parse(raw_data, source_file=str(file))

    _print_warnings(statement)

    if not statement.transactions:
        click.echo("No transactions found.", err=True)
        raise SystemExit(1)

    # Categorize
    result = categorize_transactions(
        statement.transactions,
        cfg,
        use_ai=not no_ai,
        interactive=interactive,
        prompt_fn=_interactive_prompt if interactive else None,
    )

    # Save learned keywords
    if result.learned_keywords:
        save_learned_keywords(result.learned_keywords, config_path)
        total = sum(len(kws) for kws in result.learned_keywords.values())
        click.echo(f"\nLearned {total} new keyword(s), saved to {config_path}", err=True)

    # Output
    if output:
        write_csv(result.transactions, output)
        click.echo(f"Wrote {len(result.transactions)} transactions to {output}")
    else:
        write_csv_stdout(result.transactions)


def _interactive_prompt(
    txn: Transaction,
    ai_suggestion: str | None,
    category_names: list[str],
) -> Optional[tuple[str, str]]:
    """Prompt the user to confirm or choose a category for a transaction."""
    click.echo(f"\n{'─' * 60}", err=True)
    click.echo(f"  {txn.raw_description}", err=True)
    click.echo(f"  {txn.transaction_date}  ${txn.amount}", err=True)
    click.echo(f"{'─' * 60}", err=True)

    if ai_suggestion:
        confirm = click.confirm(
            f"  AI suggests: {ai_suggestion}. Accept?",
            default=True,
            err=True,
        )
        if confirm:
            return ai_suggestion, txn.raw_description.lower()

    # Show numbered category menu
    click.echo("\n  Categories:", err=True)
    for i, name in enumerate(category_names, 1):
        click.echo(f"    {i:2d}. {name}", err=True)
    click.echo(f"    {len(category_names) + 1:2d}. skip (leave uncategorized)", err=True)

    choice = click.prompt(
        "  Enter number",
        type=int,
        err=True,
    )

    if choice < 1 or choice > len(category_names):
        return None

    chosen = category_names[choice - 1]
    return chosen, txn.raw_description.lower()


@main.group()
def config() -> None:
    """Manage categories configuration."""


@config.command("init")
@click.option("--path", "-p", type=click.Path(path_type=Path), default=None, help="Config file path")
def config_init(path: Path | None) -> None:
    """Create a default categories.yaml config file."""
    out = write_default_config(path)
    click.echo(f"Created config file: {out}")


@config.command("show")
@click.option("--path", "-p", type=click.Path(path_type=Path), default=None, help="Config file path")
def config_show(path: Path | None) -> None:
    """Display current categories configuration."""
    cfg = load_config(path)
    click.echo("Categories:")
    for name, keywords in cfg.categories.items():
        if keywords:
            click.echo(f"  {name}: {', '.join(keywords)}")
        else:
            click.echo(f"  {name}")

    click.echo(f"\nOllama model: {cfg.ollama.model}")
    click.echo(f"Ollama URL: {cfg.ollama.base_url}")
    click.echo(f"GPU layers: {'all' if cfg.ollama.num_gpu == -1 else cfg.ollama.num_gpu}")


def _read_file(path: Path) -> list[dict[str, str]]:
    """Read a file based on its extension."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_csv(path)
    elif suffix == ".pdf":
        try:
            return read_pdf(path)
        except ScannedPDFError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)
    else:
        click.echo(f"Unsupported file format: {suffix}. Supported: .csv, .pdf", err=True)
        raise SystemExit(1)


def _print_warnings(statement: ParsedStatement) -> None:
    """Print any parser warnings."""
    for warning in statement.warnings:
        click.echo(f"Warning: {warning}", err=True)
