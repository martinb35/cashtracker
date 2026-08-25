"""CashTracker CLI."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click

from cashtracker.categorizer import PromptFn, QuitInteractive, StatusFn, categorize_transactions
from cashtracker.config import load_config, save_learned_keywords, write_default_config
from cashtracker.models import Transaction
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
    """CashTracker — parse bank/credit card statements and categorize transactions.

    Reads CSV or PDF statements, extracts transactions, and assigns categories
    using keyword rules and optionally Ollama AI. Run 'cashtracker config init'
    to create a starter categories.yaml file.
    """


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None,
              help="Write CSV to this file instead of stdout.")
@click.option("--config", "-c", type=click.Path(path_type=Path), default=None,
              help="Path to categories.yaml config. Defaults to ./categories.yaml.")
@click.option("--model", "-m", type=str, default=None,
              help="Ollama model to use for AI categorization (overrides config).")
@click.option("--no-ai", is_flag=True, default=False,
              help="Skip Ollama AI; categorize using keyword rules only.")
@click.option("--interactive", "-i", is_flag=True, default=False,
              help="Prompt to confirm or choose a category for each transaction. "
                   "Press + to add a new category on the fly.")
@click.option("--recursive", "-r", is_flag=True, default=False,
              help="Recursively search subdirectories when PATH is a directory.")
@click.option("--debug-headers", is_flag=True, default=False,
              help="Print extracted column headers and row count, then exit. No transaction data is shown.")
def parse(
    path: Path,
    output: Path | None,
    config: Path | None,
    model: str | None,
    no_ai: bool,
    interactive: bool,
    recursive: bool,
    debug_headers: bool,
) -> None:
    """Parse a bank or credit card statement and categorize transactions.

    PATH is a .csv or .pdf statement file, or a directory containing
    statement files. When a directory is given, all .csv and .pdf files
    in it are parsed and combined into a single output.

    Output is CSV with columns: date, category, amount, vendor/company/item.
    Writes to stdout by default, or to a file with -o/--output.

    Categories are assigned using keyword rules from categories.yaml. Use
    --no-ai to skip Ollama, or -i/--interactive to confirm each assignment.

    \b
    Examples:
      cashtracker parse statement.pdf
      cashtracker parse statement.csv -o categorized.csv
      cashtracker parse statements/              # parse all files in folder
      cashtracker parse statements/ -r           # recurse into subfolders
      cashtracker parse statement.pdf --no-ai
      cashtracker parse statement.pdf -i -m llama3
    """
    cfg = load_config(config)
    config_path = Path(config) if config else Path("categories.yaml")
    if model:
        cfg.ollama.model = model

    # Collect files to parse
    if path.is_dir():
        glob_fn = path.rglob if recursive else path.glob
        files = sorted(
            f for f in glob_fn("*")
            if f.is_file() and f.suffix.lower() in (".csv", ".pdf") and not f.name.startswith(".")
        )
        if not files:
            click.echo(f"No .csv or .pdf files found in {path}", err=True)
            raise SystemExit(1)
        click.echo(f"Found {len(files)} statement file(s) in {path}", err=True)
    else:
        files = [path]

    if debug_headers:
        for f in files:
            raw_data = _read_file(f)
            click.echo(f"\n{f.name}:")
            if raw_data:
                click.echo(f"  Extracted {len(raw_data)} rows")
                click.echo(f"  Column headers: {list(raw_data[0].keys())}")
            else:
                click.echo("  No data extracted.")
        return

    # Parse all files and collect transactions
    all_transactions: list[Transaction] = []
    all_warnings: list[str] = []
    for f in files:
        raw_data = _read_file(f)
        statement = detect_and_parse(raw_data, source_file=str(f))
        all_warnings.extend(statement.warnings)
        if statement.transactions:
            all_transactions.extend(statement.transactions)
            click.echo(f"  {f.name}: {len(statement.transactions)} transactions", err=True)
        else:
            click.echo(f"  {f.name}: no transactions found", err=True)

    # Print warnings
    for warning in all_warnings:
        click.echo(f"Warning: {warning}", err=True)

    if not all_transactions:
        click.echo("No transactions found.", err=True)
        raise SystemExit(1)

    # Categorize
    def _save_keywords(learned: dict[str, list[str]]) -> None:
        save_learned_keywords(learned, config_path)

    def _show_status(total: int, auto: int) -> None:
        click.echo(f"{total} transactions, {auto} auto-categorized", err=True)

    result = categorize_transactions(
        all_transactions,
        cfg,
        use_ai=not no_ai,
        interactive=interactive,
        prompt_fn=_interactive_prompt if interactive else None,
        save_fn=_save_keywords if interactive else None,
        status_fn=_show_status if interactive else None,
    )

    # Report saved keywords
    if result.learned_keywords:
        if not interactive:
            # Non-interactive mode: save at the end
            save_learned_keywords(result.learned_keywords, config_path)
        total = sum(len(kws) for kws in result.learned_keywords.values())
        click.echo(f"\nLearned {total} new keyword(s), saved to {config_path}", err=True)

    # Output
    count = len(result.transactions)
    if output:
        write_csv(result.transactions, output)
        click.echo(f"Wrote {count} transactions to {output}", err=True)
    else:
        write_csv_stdout(result.transactions)
        click.echo(f"Parsed {count} transactions", err=True)


def _interactive_prompt(
    txn: Transaction,
    ai_suggestion: str | None,
    category_names: list[str],
    current: int,
    total: int,
) -> Optional[tuple[str, str]]:
    """Prompt the user to confirm or choose a category for a transaction.
    
    Single keypress — no Enter required.
    """
    click.echo(f"\n{'─' * 60}", err=True)
    click.echo(f"  [{current}/{total}] {txn.raw_description}", err=True)
    click.echo(f"  {txn.transaction_date}  ${txn.amount}", err=True)
    click.echo(f"{'─' * 60}", err=True)

    if ai_suggestion:
        click.echo(f"  AI suggests: {ai_suggestion}. [y/n] ", err=True, nl=False)
        ch = _getch()
        click.echo(ch, err=True)
        if ch in ("q", "\x1b"):
            raise QuitInteractive()
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
    click.echo(f"    +  add new category", err=True)
    click.echo(f"    0. skip (leave uncategorized)", err=True)

    click.echo("  Press key: ", err=True, nl=False)
    ch = _getch()
    click.echo(ch, err=True)

    if ch in ("q", "\x1b"):
        raise QuitInteractive()

    if ch == "0":
        return None

    if ch == "+":
        new_name = click.prompt("  Category name", err=True).strip().lower()
        if not new_name:
            return None
        category_names.append(new_name)
        return new_name, txn.raw_description.lower()

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
    """Manage the categories.yaml configuration file."""


@config.command("init")
@click.option("--path", "-p", type=click.Path(path_type=Path), default=None,
              help="Config file path. Defaults to ./categories.yaml.")
def config_init(path: Path | None) -> None:
    """Create a default categories.yaml config file.

    Writes a starter config with common categories (dining, shopping, etc.)
    and default Ollama settings. Will not overwrite an existing file.
    """
    out = write_default_config(path)
    click.echo(f"Created config file: {out}")


@config.command("show")
@click.option("--path", "-p", type=click.Path(path_type=Path), default=None,
              help="Config file path. Defaults to ./categories.yaml.")
def config_show(path: Path | None) -> None:
    """Display current categories, keywords, and Ollama settings."""
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



