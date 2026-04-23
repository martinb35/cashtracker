"""Generic CSV normalizer — heuristic parser for common CSV statement layouts."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from cashtracker.models import ParsedStatement, StatementMetadata, Transaction
from cashtracker.parsers.base import StatementNormalizer

# Common header patterns
DATE_PATTERNS = re.compile(
    r"^(date|trans\.?\s*date|transaction\s*date|posting\s*date|posted|post\s*date|effective\s*date)$",
    re.IGNORECASE,
)
AMOUNT_PATTERNS = re.compile(
    r"^(amount|transaction\s*amount|charge|payment)$",
    re.IGNORECASE,
)
DESCRIPTION_PATTERNS = re.compile(
    r"^(description|memo|narrative|details|transaction\s*description|payee|merchant|vendor|name)$",
    re.IGNORECASE,
)

DATE_FORMATS = [
    "%m/%d/%Y",
    "%m/%d/%y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m-%d-%Y",
    "%Y/%m/%d",
    "%b %d, %Y",
    "%d %b %Y",
    "%m/%d",
]


class GenericCSVNormalizer(StatementNormalizer):
    """Heuristic normalizer for common CSV statement formats.

    Detects date, amount, and description columns by header name patterns.
    This is the fallback normalizer when no institution-specific match is found.
    """

    def can_handle(self, raw_data: list[dict[str, str]], metadata: dict[str, Any] | None = None) -> float:
        if not raw_data:
            return 0.0

        headers = set(raw_data[0].keys())
        date_col = _find_column(headers, DATE_PATTERNS)
        amount_col = _find_column(headers, AMOUNT_PATTERNS)
        desc_col = _find_column(headers, DESCRIPTION_PATTERNS)

        if date_col and amount_col:
            return 0.5 if desc_col else 0.3

        return 0.0

    def normalize(self, raw_data: list[dict[str, str]], source_file: str = "") -> ParsedStatement:
        if not raw_data:
            return ParsedStatement(source_file=source_file)

        headers = set(raw_data[0].keys())
        date_col = _find_column(headers, DATE_PATTERNS)
        amount_col = _find_column(headers, AMOUNT_PATTERNS)
        desc_col = _find_column(headers, DESCRIPTION_PATTERNS)

        # Also look for separate debit/credit columns
        debit_col = _find_column(headers, re.compile(r"^(debit|withdrawal|charge)$", re.IGNORECASE))
        credit_col = _find_column(headers, re.compile(r"^(credit|deposit|payment)$", re.IGNORECASE))

        if not date_col:
            return ParsedStatement(
                source_file=source_file,
                warnings=["Could not detect a date column"],
            )

        transactions = []
        warnings = []

        for i, row in enumerate(raw_data):
            try:
                txn_date = _parse_date(row.get(date_col, ""))
                if txn_date is None:
                    warnings.append(f"Row {i + 1}: could not parse date '{row.get(date_col, '')}'")
                    continue

                amount = _parse_amount(row, amount_col, debit_col, credit_col)
                if amount is None:
                    warnings.append(f"Row {i + 1}: could not parse amount")
                    continue

                description = row.get(desc_col, "") if desc_col else ""

                txn = Transaction(
                    transaction_date=txn_date,
                    raw_description=description,
                    amount=amount,
                    source_file=source_file,
                )
                transactions.append(txn)

            except Exception as e:
                warnings.append(f"Row {i + 1}: error processing row: {e}")

        return ParsedStatement(
            transactions=transactions,
            metadata=StatementMetadata(),
            warnings=warnings,
            source_file=source_file,
        )


def _find_column(headers: set[str], pattern: re.Pattern) -> str | None:
    """Find the first column header matching a pattern."""
    for header in headers:
        if pattern.match(header.strip()):
            return header
    return None


def _parse_date(value: str) -> date | None:
    """Try parsing a date string with common formats."""
    value = value.strip()
    if not value:
        return None

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(
    row: dict[str, str],
    amount_col: str | None,
    debit_col: str | None,
    credit_col: str | None,
) -> Decimal | None:
    """Parse an amount from a row, handling single-column and debit/credit layouts."""
    if amount_col:
        val = _clean_amount(row.get(amount_col, ""))
        if val is not None:
            return val

    # Try separate debit/credit columns
    if debit_col or credit_col:
        debit = _clean_amount(row.get(debit_col, "")) if debit_col else None
        credit = _clean_amount(row.get(credit_col, "")) if credit_col else None
        if debit is not None:
            return -abs(debit)
        if credit is not None:
            return abs(credit)

    return None


def _clean_amount(value: str) -> Decimal | None:
    """Clean and parse an amount string."""
    if not value or not value.strip():
        return None

    cleaned = value.strip().replace("$", "").replace(",", "").replace(" ", "")

    # Handle parenthetical negatives: (123.45) -> -123.45
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None
