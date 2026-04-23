"""CashTracker CLI."""

from __future__ import annotations

import sys
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


def _getch() -> str:
    """Read a single keypress without requiring Enter."""
    if sys.platform == "win32":
        import msvcrt
        ch = msvcrt.getwch()
    else:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


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
    def _save_keywords(learned: dict[str, list[str]]) -> None:
        save_learned_keywords(learned, config_path)

    result = categorize_transactions(
        statement.transactions,
        cfg,
        use_ai=not no_ai,
        interactive=interactive,
        prompt_fn=_interactive_prompt if interactive else None,
        save_fn=_save_keywords if interactive else None,
    )

    # Report saved keywords
    if result.learned_keywords:
        if not interactive:
            # Non-interactive mode: save at the end
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
    """Prompt the user to confirm or choose a category for a transaction.
    
    Single keypress — no Enter required.
    """
    click.echo(f"\n{'─' * 60}", err=True)
    click.echo(f"  {txn.raw_description}", err=True)
    click.echo(f"  {txn.transaction_date}  ${txn.amount}", err=True)
    click.echo(f"{'─' * 60}", err=True)

    if ai_suggestion:
        click.echo(f"  AI suggests: {ai_suggestion}. [y/n] ", err=True, nl=False)
        ch = _getch()
        click.echo(ch, err=True)
        if ch.lower() != "n":
            return ai_suggestion, txn.raw_description.lower()

    # Show numbered category menu with single-key selection
    click.echo("\n  Categories:", err=True)
    # Map keys: 1-9 then a, b, c... for 10+
    keys: list[str] = []
    for i in range(len(category_names)):
        if i < 9:
            keys.append(str(i + 1))
        else:
            keys.append(chr(ord("a") + i - 9))

    for i, name in enumerate(category_names):
        click.echo(f"    {keys[i]}. {name}", err=True)
    click.echo(f"    0. skip (leave uncategorized)", err=True)

    click.echo("  Press key: ", err=True, nl=False)
    ch = _getch()
    click.echo(ch, err=True)

    if ch == "0":
        return None

    try:
        idx = keys.index(ch.lower())
    except ValueError:
        return None

    if idx >= len(category_names):
        return None

    chosen = category_names[idx]
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
