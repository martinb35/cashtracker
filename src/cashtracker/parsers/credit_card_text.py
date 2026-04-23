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

# Billing period date extraction — supports MM/DD/YY and MM/DD/YYYY
_BILLING_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})")
_MONTH_YEAR = re.compile(
    r"(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+(20\d{2})\b",
    re.IGNORECASE,
)
_DATE_4DIGIT_YEAR = re.compile(r"\d{1,2}/\d{1,2}/(20\d{2})\b")
_DATE_2DIGIT_YEAR = re.compile(r"\d{1,2}/\d{1,2}/(\d{2})\b")

# Section headers to skip
_SECTION_HEADERS = {
    "account summary", "payments, credits and adjustments",
    "standard purchases", "fees charged", "interest charged",
    "total", "totals", "new balance", "previous balance",
    "minimum payment", "payment due",
}

# Lines containing these phrases are summary/rewards text, not transaction continuations
_SUMMARY_NOISE = re.compile(
    r"year\s+to\s+date|cash\s+back\s+reward|reward.*balance|"
    r"certificate\s+amount|earned\s+this\s+period|summary",
    re.IGNORECASE,
)
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
        billing_period = _detect_billing_period(lines)
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

            # Find the amount (first occurrence — the transaction amount)
            amount_matches = list(_AMOUNT_PATTERN.finditer(all_text))
            if not amount_matches:
                warnings.append(f"No amount found for transaction starting: {first_line[:60]}")
                continue

            amount_match = amount_matches[0]
            amount_str = amount_match.group(1)

            # Description is everything before the amount
            desc_before = all_text[:amount_match.start()].strip()
            description = desc_before

            # Strip any summary noise from description
            noise_match = _SUMMARY_NOISE.search(description)
            if noise_match:
                description = description[:noise_match.start()].strip()

            if not description:
                description = "(no description)"

            # Skip payment/credit transactions
            if _PAYMENT_PATTERNS.match(description):
                continue

            txn = _build_transaction(
                sale_date_str, post_date_str, description,
                amount_str, billing_period, statement_year, source_file, warnings,
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
        elif current_block and not _SUMMARY_NOISE.search(stripped):
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
    billing_period: tuple[int, int, int, int] | None,
    fallback_year: int,
    source_file: str,
    warnings: list[str],
) -> Transaction | None:
    """Build a Transaction from parsed components."""
    try:
        txn_date = _parse_mmdd(sale_date_str, billing_period, fallback_year)
    except ValueError:
        warnings.append(f"Could not parse date: {sale_date_str}")
        return None

    posted = None
    if post_date_str:
        try:
            posted = _parse_mmdd(post_date_str, billing_period, fallback_year)
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


def _extract_year_from_line(line: str) -> int | None:
    """Extract a year from a line, supporting both 2-digit and 4-digit years."""
    matches_4 = _DATE_4DIGIT_YEAR.findall(line)
    if matches_4:
        return int(matches_4[-1])
    matches_2 = _DATE_2DIGIT_YEAR.findall(line)
    if matches_2:
        yy = int(matches_2[-1])
        return 2000 + yy if yy < 80 else 1900 + yy
    return None


def _to_full_year(yy_or_yyyy: int) -> int:
    """Convert a 2-digit or 4-digit year to a full 4-digit year."""
    if yy_or_yyyy < 80:
        return 2000 + yy_or_yyyy
    if yy_or_yyyy < 100:
        return 1900 + yy_or_yyyy
    return yy_or_yyyy


def _detect_billing_period(lines: list[str]) -> tuple[int, int, int, int] | None:
    """Detect billing period and return (start_month, start_year, end_month, end_year).
    
    Returns None if no billing period found.
    """
    billing_re = re.compile(
        r"(?:billing|statement)\s+(?:period|date|closing)", re.IGNORECASE
    )
    for line in lines[:30]:
        if billing_re.search(line):
            dates = _BILLING_DATE.findall(line)
            if len(dates) >= 2:
                sm, _, sy = dates[0]
                em, _, ey = dates[1]
                return (int(sm), _to_full_year(int(sy)),
                        int(em), _to_full_year(int(ey)))
            elif len(dates) == 1:
                em, _, ey = dates[0]
                return (None, None, int(em), _to_full_year(int(ey)))
    return None


def _detect_year(lines: list[str]) -> int:
    """Fallback: detect a single year from header lines."""
    for line in lines[:30]:
        match = _MONTH_YEAR.search(line)
        if match:
            return int(match.group(1))
    for line in lines[:30]:
        year = _extract_year_from_line(line)
        if year:
            return year
    from datetime import date as _date
    return _date.today().year


def _resolve_year(month: int, billing_period: tuple[int, int, int, int] | None,
                  fallback_year: int) -> int:
    """Pick the correct year for a transaction month given a billing period.
    
    If the billing period spans a year boundary (e.g. Dec 2024 - Jan 2025),
    months >= start_month get start_year, months <= end_month get end_year.
    """
    if billing_period is None:
        return fallback_year

    start_month, start_year, end_month, end_year = billing_period
    if start_month is None:
        return end_year

    if start_year == end_year:
        return end_year

    # Year boundary: e.g. start=Dec 2024, end=Jan 2025
    if month >= start_month:
        return start_year
    else:
        return end_year


def _parse_mmdd(value: str, billing_period: tuple[int, int, int, int] | None,
                fallback_year: int) -> date:
    """Parse MM/DD with the correct year based on billing period."""
    parts = value.strip().split("/")
    if len(parts) != 2:
        raise ValueError(f"Invalid date: {value}")
    month, day = int(parts[0]), int(parts[1])
    year = _resolve_year(month, billing_period, fallback_year)
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
