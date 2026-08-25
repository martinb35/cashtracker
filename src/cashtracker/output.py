"""CSV output writer."""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

from cashtracker.models import Transaction


def write_csv(
    transactions: list[Transaction],
    output_path: Path | None = None,
) -> str:
    """Write transactions to CSV.

    Output columns: date, category, amount, vendor/company/item

    If output_path is None, returns the CSV as a string.
    Otherwise writes to the file and returns the path as a string.
    """
    if output_path:
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            _write_rows(f, transactions)
        return str(output_path)
    else:
        buf = io.StringIO()
        _write_rows(buf, transactions)
        return buf.getvalue()


def write_csv_stdout(transactions: list[Transaction]) -> None:
    """Write transactions as CSV to stdout."""
    _write_rows(sys.stdout, transactions)


def _write_rows(f, transactions: list[Transaction]) -> None:
    """Write transaction rows to a file-like object."""
    writer = csv.writer(f)
    writer.writerow(["date", "category", "amount", "vendor/company/item"])
    for txn in transactions:
        writer.writerow([
            txn.transaction_date.isoformat(),
            txn.category,
            str(txn.amount),
            txn.vendor_display,
        ])
