"""Credit card statement normalizer — parses text-line PDF statements."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from cashtracker.models import ParsedStatement, StatementMetadata, Transaction
from cashtracker.parsers.base import StatementNormalizer

# Line starting with a date: 12/19 or 12/19 12/19
_DATE_START = re.compile(
    r"^(\d{1,2}/\d{1,2})\s+"           # sale date (MM/DD)
    r"(?:(\d{1,2}/\d{1,2})\s+)?"       # optional post date (MM/DD)
)

# Amount pattern anywhere in text: $13.48, -$609.87, $1,234.56
_AMOUNT_PATTERN = re.compile(r"(-?\$[\d,]+\.\d{2})")

# Statement year detection from header lines
_YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")

# Section headers to skip
_SECTION_HEADERS = {
    "account summary", "payments, credits and adjustments",
    "standard purchases", "fees charged", "interest charged",
    "total", "totals", "new balance", "previous balance",
    "minimum payment", "payment due",
}

# Transaction descriptions that indicate payments to skip (not credits/returns)
_PAYMENT_PATTERNS = re.compile(
    r"^(payment\s+thank\s+you|autopay|automatic\s+payment|payment\s+received|"
    r"balance\s+transfer|returned\s+payment)",
    re.IGNORECASE,
)


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
        matches = sum(1 for line in lines if _DATE_START.match(line))
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

        # Group lines into transaction blocks.
        # A new block starts when a line begins with a date pattern.
        blocks = _group_into_blocks(lines)

        for block_lines in blocks:
            first_line = block_lines[0]
            date_match = _DATE_START.match(first_line)
            if not date_match:
                continue

            sale_date_str = date_match.group(1)
            post_date_str = date_match.group(2)

            # Join all lines into one text, then extract amount and description
            # Remove the date prefix from the first line
            remaining = first_line[date_match.end():]
            all_text = " ".join([remaining] + block_lines[1:]).strip()

            # Find the amount (last occurrence to handle edge cases)
            amount_matches = list(_AMOUNT_PATTERN.finditer(all_text))
            if not amount_matches:
                warnings.append(f"No amount found for transaction starting: {first_line[:60]}")
                continue

            # Use the last amount found (the transaction amount, not intermediate text)
            amount_match = amount_matches[-1]
            amount_str = amount_match.group(1)

            # Description is everything except the amount
            desc_before = all_text[:amount_match.start()].strip()
            desc_after = all_text[amount_match.end():].strip()
            description = desc_before
            # Append trailing text if it's meaningful (not just noise)
            if desc_after and not _is_trailing_noise(desc_after):
                description = f"{description} {desc_after}".strip()

            if not description:
                description = "(no description)"

            # Skip payment/credit transactions
            if _PAYMENT_PATTERNS.match(description):
                continue

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


def _group_into_blocks(lines: list[str]) -> list[list[str]]:
    """Group lines into transaction blocks.

    A new block starts when a line begins with a date pattern (MM/DD).
    Continuation lines (indented or non-date lines) are appended to the current block.
    Section headers and empty lines are skipped.
    """
    blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or _is_section_header(stripped):
            continue

        if _DATE_START.match(stripped):
            if current_block:
                blocks.append(current_block)
            current_block = [stripped]
        elif current_block:
            current_block.append(stripped)

    if current_block:
        blocks.append(current_block)

    return blocks


def _is_trailing_noise(text: str) -> bool:
    """Check if trailing text after the amount is noise to ignore."""
    noise = {"tot", "total", "subtotal"}
    return text.lower().strip() in noise


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
