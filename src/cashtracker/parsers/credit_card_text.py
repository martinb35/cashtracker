"""Credit card statement normalizer — parses text-line PDF statements."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from cashtracker.models import ParsedStatement, StatementMetadata, Transaction
from cashtracker.parsers.base import StatementNormalizer

# Single-line transaction: 12/19 12/19 CHICK-FIL-A #03801 $13.48
_TXN_SINGLE_LINE = re.compile(
    r"^(\d{1,2}/\d{1,2})\s+"           # sale date (MM/DD)
    r"(?:(\d{1,2}/\d{1,2})\s+)?"       # optional post date (MM/DD)
    r"(.+?)\s+"                          # description
    r"(-?\$[\d,]+\.\d{2})$"             # amount ($XX.XX or -$XX.XX)
)

# Start of a multi-line transaction: 12/29 12/29 PIE FOR THE PEOPLE NW    SNOQUALMIE
_TXN_START = re.compile(
    r"^(\d{1,2}/\d{1,2})\s+"           # sale date (MM/DD)
    r"(?:(\d{1,2}/\d{1,2})\s+)?"       # optional post date (MM/DD)
    r"(.+)$"                             # description start (rest of line)
)

# Amount on a continuation line: PAWA $63.35
_AMOUNT_LINE = re.compile(r"(-?\$[\d,]+\.\d{2})\s*$")

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

    Handles single-line and multi-line transaction formats:
        MM/DD [MM/DD] DESCRIPTION $AMOUNT
        MM/DD [MM/DD] DESCRIPTION_START LOCATION
         CONTINUATION $AMOUNT
    """

    def can_handle(self, raw_data: list[dict[str, str]], metadata: dict[str, Any] | None = None) -> float:
        if not raw_data or "_raw_line" not in raw_data[0]:
            return 0.0

        lines = [row.get("_raw_line", "") for row in raw_data]
        matches = sum(1 for line in lines if _TXN_SINGLE_LINE.match(line) or _TXN_START.match(line))
        if matches == 0:
            return 0.0
        if matches >= 3:
            return 0.7
        if matches >= 1:
            return 0.4
        return 0.0

    def normalize(self, raw_data: list[dict[str, str]], source_file: str = "") -> ParsedStatement:
        lines = [row["_raw_line"] for row in raw_data if "_raw_line" in row]

        statement_year = _detect_year(lines)
        transactions = []
        warnings = []

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            i += 1

            if not line or _is_section_header(line):
                continue

            # Try single-line match first
            match = _TXN_SINGLE_LINE.match(line)
            if match:
                sale_date_str, post_date_str, description, amount_str = match.groups()
                txn = _build_transaction(
                    sale_date_str, post_date_str, description.strip(),
                    amount_str, statement_year, source_file, warnings,
                )
                if txn:
                    transactions.append(txn)
                continue

            # Try multi-line: line starts with date but no amount
            start_match = _TXN_START.match(line)
            if not start_match:
                continue

            sale_date_str, post_date_str, desc_start = start_match.groups()
            description_parts = [desc_start.strip()]
            amount_str = None

            # Collect continuation lines until we find an amount
            while i < len(lines):
                next_line = lines[i].strip()

                # If next line starts a new transaction, stop
                if _TXN_START.match(next_line) and not _is_continuation(next_line):
                    break

                i += 1

                # Check if this continuation line has the amount
                amount_match = _AMOUNT_LINE.search(next_line)
                if amount_match:
                    amount_str = amount_match.group(1)
                    # Text before the amount is part of the description
                    desc_part = next_line[:amount_match.start()].strip()
                    if desc_part:
                        description_parts.append(desc_part)
                    break
                elif next_line and not _is_section_header(next_line):
                    description_parts.append(next_line)

            if amount_str is None:
                warnings.append(f"No amount found for transaction starting: {line[:50]}")
                continue

            description = " ".join(description_parts)
            txn = _build_transaction(
                sale_date_str, post_date_str, description,
                amount_str, statement_year, source_file, warnings,
            )
            if txn:
                transactions.append(txn)

        return ParsedStatement(
            transactions=transactions,
            metadata=StatementMetadata(),
            warnings=warnings,
            source_file=source_file,
        )


def _is_continuation(line: str) -> bool:
    """Check if a line that matches _TXN_START is actually a continuation line.

    Continuation lines that happen to start with MM/DD are rare,
    but we check if the line starts with whitespace (indented continuation).
    """
    return line != line.lstrip()


def _build_transaction(
    sale_date_str: str,
    post_date_str: str | None,
    description: str,
    amount_str: str,
    statement_year: int,
    source_file: str,
    warnings: list[str],
) -> Transaction | None:
    """Build a Transaction from parsed components."""
    try:
        txn_date = _parse_mmdd(sale_date_str, statement_year)
    except ValueError:
        warnings.append(f"Could not parse date: {sale_date_str}")
        return None

    posted = None
    if post_date_str:
        try:
            posted = _parse_mmdd(post_date_str, statement_year)
        except ValueError:
            pass

    amount = _parse_amount(amount_str)
    if amount is None:
        warnings.append(f"Could not parse amount: {amount_str}")
        return None

    return Transaction(
        transaction_date=txn_date,
        posted_date=posted,
        raw_description=description,
        amount=amount,
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
