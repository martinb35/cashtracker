"""CSV file reader — extracts raw rows from CSV files."""

from __future__ import annotations

import csv
import io
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV file and return rows as a list of dicts.

    Auto-detects delimiter and handles common encodings.
    """
    text = _read_text(path)
    dialect = _detect_dialect(text)
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = []
    for row in reader:
        # Strip whitespace from keys and values
        cleaned = {k.strip(): v.strip() if v else "" for k, v in row.items() if k}
        rows.append(cleaned)
    return rows


def _read_text(path: Path) -> str:
    """Read file text, trying common encodings."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"Cannot decode {path} with any supported encoding")


def _detect_dialect(text: str) -> csv.Dialect:
    """Detect CSV dialect (delimiter, quoting) from sample text."""
    try:
        sample = text[:8192]
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel
