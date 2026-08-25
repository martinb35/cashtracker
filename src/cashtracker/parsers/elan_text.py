"""Elan Financial Services statement normalizer (Fidelity Visa, etc.).

Parses text-line PDF statements from Elan Financial Services.
Each transaction is a single line:
    MM/DD MM/DD REFNUM DESCRIPTION LOCATION STATE $AMOUNT[CR]

Credits (returns, payments) have a ``CR`` suffix on the amount.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from cashtracker.models import ParsedStatement, StatementMetadata, Transaction
from cashtracker.parsers.base import StatementNormalizer
from cashtracker.vendor_normalizer import normalize_vendor

# Elan transaction line:  MM/DD MM/DD REFNUM DESCRIPTION $AMOUNT[CR]
_ELAN_TXN = re.compile(
    r"^(\d{1,2}/\d{1,2})\s+"          # post date
    r"(\d{1,2}/\d{1,2})\s+"           # trans date
    r"\d{4}\s+"                        # 4-digit ref number (discard)
    r"(.+)\s+"                         # description (greedy)
    r"\$([0-9,]+\.\d{2})(CR)?$"        # amount, optional CR suffix
)

# Elan identifier — appears on every page
_ELAN_MARKER = re.compile(
    r"elan\s+financial\s+services|"
    r"1-888-551-5144",
    re.IGNORECASE,
)

# Section headers that contain transactions
_TXN_SECTION = re.compile(
    r"purchases\s+and\s+other\s+debits|"
    r"payments\s+and\s+other\s+credits",
    re.IGNORECASE,
)

# Lines to skip
_SKIP_LINE = re.compile(
    r"^post\s+trans|"                  # column header "Post Trans"
    r"^date\s+date\s+ref|"            # column header "Date Date Ref #..."
    r"^total\s+this\s+period|"         # "TOTAL THIS PERIOD $6,352.29"
    r"^merchandise/service\s+return|"  # sub-description for returns
    r"^\d{4}\s+totals|"               # "2025 Totals Year-to-Date"
    r"^total\s+fees|^total\s+interest",
    re.IGNORECASE,
)

# Billing period from page header:  "12/04/2024 -01/03/2025"
_BILLING_PERIOD = re.compile(
    r"(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(\d{1,2}/\d{1,2}/\d{4})"
)

# Statement year from header: "January2025 Statement" or "January 2025 Statement"
_STMT_YEAR = re.compile(
    r"(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\s*(\d{4})\s+statement",
    re.IGNORECASE,
)


class ElanTextNormalizer(StatementNormalizer):
    """Normalizer for Elan Financial Services PDF statements (Fidelity Visa, etc.)."""

    def can_handle(self, raw_data: list[dict[str, str]], metadata: dict[str, Any] | None = None) -> float:
        if not raw_data or "_raw_line" not in raw_data[0]:
            return 0.0

        lines = [row.get("_raw_line", "") for row in raw_data]
        has_elan = any(_ELAN_MARKER.search(line) for line in lines)
        if not has_elan:
            return 0.0

        txn_count = sum(1 for line in lines if _ELAN_TXN.match(line))
        if txn_count >= 3:
            return 0.9  # Higher than CreditCardTextNormalizer's 0.7
        if txn_count >= 1:
            return 0.5
        return 0.0

    def normalize(self, raw_data: list[dict[str, str]], source_file: str = "") -> ParsedStatement:
        lines = [row["_raw_line"] for row in raw_data if "_raw_line" in row]

        statement_year = _detect_year(lines)
        billing_start, billing_end = _detect_billing_period(lines)
        transactions: list[Transaction] = []
        warnings: list[str] = []

        for line in lines:
            if _SKIP_LINE.match(line):
                continue

            m = _ELAN_TXN.match(line)
            if not m:
                continue

            post_date_str = m.group(1)
            trans_date_str = m.group(2)
            description = m.group(3).strip()
            amount_str = m.group(4).replace(",", "")
            is_credit = m.group(5) is not None

            try:
                amount = Decimal(amount_str)
            except InvalidOperation:
                warnings.append(f"Bad amount '{amount_str}' in: {line[:60]}")
                continue

            # Credits are negative (payments, returns)
            if is_credit:
                amount = -amount

            trans_date = _parse_mmdd(trans_date_str, statement_year, billing_end)
            post_date = _parse_mmdd(post_date_str, statement_year, billing_end)

            vendor = normalize_vendor(description)

            transactions.append(Transaction(
                transaction_date=trans_date,
                raw_description=description,
                amount=amount,
                normalized_vendor=vendor,
                posted_date=post_date,
                source_file=source_file,
            ))

        metadata = StatementMetadata(
            institution="Elan Financial Services",
            statement_period_start=billing_start,
            statement_period_end=billing_end,
        )

        return ParsedStatement(
            transactions=transactions,
            metadata=metadata,
            warnings=warnings,
            source_file=source_file,
        )


def _detect_year(lines: list[str]) -> int:
    """Extract statement year from header lines."""
    for line in lines:
        m = _STMT_YEAR.search(line)
        if m:
            return int(m.group(1))
    for line in lines:
        m = _BILLING_PERIOD.search(line)
        if m:
            parts = m.group(2).split("/")
            return int(parts[2])
    return date.today().year


def _detect_billing_period(lines: list[str]) -> tuple[date | None, date | None]:
    """Extract billing period start/end dates."""
    for line in lines:
        m = _BILLING_PERIOD.search(line)
        if m:
            try:
                start = _parse_date_full(m.group(1))
                end = _parse_date_full(m.group(2))
                return start, end
            except (ValueError, IndexError):
                pass
    return None, None


def _parse_date_full(s: str) -> date:
    """Parse MM/DD/YYYY."""
    parts = s.split("/")
    month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
    return date(year, month, day)


def _parse_mmdd(s: str, statement_year: int, billing_end: date | None) -> date:
    """Parse MM/DD and assign correct year based on billing context.

    Handles year boundaries — e.g., a December transaction on a January statement.
    """
    parts = s.split("/")
    month, day = int(parts[0]), int(parts[1])

    if billing_end:
        # If the transaction month is much later than billing end month,
        # it's probably from the previous year (Dec txn on Jan statement)
        if month > billing_end.month + 1:
            return date(billing_end.year - 1, month, day)
        return date(billing_end.year, month, day)

    return date(statement_year, month, day)
