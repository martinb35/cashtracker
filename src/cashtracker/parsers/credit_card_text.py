"""Credit card statement normalizer — parses text-line PDF statements."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from cashtracker.models import ParsedStatement, StatementMetadata, Transaction
from cashtracker.parsers.base import StatementNormalizer

# Matches lines like: 12/19 12/19 CHICK-FIL-A #03801 ... $13.48
# Or: 01/13 PAYMENT THANK YOU -$609.87
_TXN_LINE = re.compile(
    r"^(\d{1,2}/\d{1,2})\s+"           # sale date (MM/DD)
    r"(?:(\d{1,2}/\d{1,2})\s+)?"       # optional post date (MM/DD)
    r"(.+?)\s+"                          # description
    r"(-?\$[\d,]+\.\d{2})$"             # amount ($XX.XX or -$XX.XX)
)

# Statement year detection from header lines
_YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")

# Section headers to skip
_SECTION_HEADERS = {
    "account summary", "payments, credits and adjustments",
    "standard purchases", "fees charged", "interest charged",
    "total", "totals", "new balance", "previous balance",
    "minimum payment", "payment due",
}


class CreditCardTextNormalizer(StatementNormalizer):
    """Normalizer for credit card PDF statements extracted as text lines.

    Handles the common format:
        MM/DD [MM/DD] DESCRIPTION $AMOUNT
    """

    def can_handle(self, raw_data: list[dict[str, str]], metadata: dict[str, Any] | None = None) -> float:
        if not raw_data or "_raw_line" not in raw_data[0]:
            return 0.0

        # Score based on how many lines match the transaction pattern
        matches = sum(1 for row in raw_data if _TXN_LINE.match(row.get("_raw_line", "")))
        if matches == 0:
            return 0.0

        ratio = matches / len(raw_data)
        # Even a few matches in a multi-page statement is a good signal
        if matches >= 3:
            return 0.7
        if matches >= 1:
            return 0.4
        return ratio * 0.5

    def normalize(self, raw_data: list[dict[str, str]], source_file: str = "") -> ParsedStatement:
        lines = [row["_raw_line"] for row in raw_data if "_raw_line" in row]

        statement_year = _detect_year(lines)
        transactions = []
        warnings = []

        for line in lines:
            line = line.strip()
            if not line or _is_section_header(line):
                continue

            match = _TXN_LINE.match(line)
            if not match:
                continue

            sale_date_str, post_date_str, description, amount_str = match.groups()

            try:
                txn_date = _parse_mmdd(sale_date_str, statement_year)
            except ValueError:
                warnings.append(f"Could not parse date: {sale_date_str}")
                continue

            posted = None
            if post_date_str:
                try:
                    posted = _parse_mmdd(post_date_str, statement_year)
                except ValueError:
                    pass

            amount = _parse_amount(amount_str)
            if amount is None:
                warnings.append(f"Could not parse amount: {amount_str}")
                continue

            description = description.strip()

            transactions.append(Transaction(
                transaction_date=txn_date,
                posted_date=posted,
                raw_description=description,
                amount=amount,
                source_file=source_file,
            ))

        return ParsedStatement(
            transactions=transactions,
            metadata=StatementMetadata(),
            warnings=warnings,
            source_file=source_file,
        )


def _detect_year(lines: list[str]) -> int:
    """Try to detect the statement year from header lines."""
    for line in lines[:15]:
        match = _YEAR_PATTERN.search(line)
        if match:
            return int(match.group(1))

    from datetime import date as _date
    return _date.today().year


def _parse_mmdd(value: str, year: int) -> date:
    """Parse MM/DD with an assumed year."""
    parts = value.strip().split("/")
    if len(parts) != 2:
        raise ValueError(f"Invalid date: {value}")
    month, day = int(parts[0]), int(parts[1])
    return date(year, month, day)


def _parse_amount(value: str) -> Decimal | None:
    """Parse amount like $13.48 or -$609.87."""
    cleaned = value.strip().replace("$", "").replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _is_section_header(line: str) -> bool:
    """Check if a line is a section header to skip."""
    return line.lower().strip() in _SECTION_HEADERS
