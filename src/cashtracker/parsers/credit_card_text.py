"""Credit card statement normalizer — parses text-line PDF statements."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from cashtracker.config import load_personal_config
from cashtracker.models import ParsedStatement, StatementMetadata, Transaction
from cashtracker.parsers.base import StatementNormalizer
from cashtracker.vendor_normalizer import normalize_vendor

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
    "purchases", "advances", "account messages",
}

# Lines containing these phrases are summary/rewards text, not transaction continuations
_SUMMARY_NOISE = re.compile(
    r"year[\s-]+to[\s-]+date|cash\s+back\s+reward|reward.*balance|"
    r"certificate\s+amount|earned\s+this\s+period|\bsummary\b|"
    r"total\s+fees|total\s+interest|interest\s+charge|"
    r"annual\s+percentage|billing\s+cycle|balance\s+subject|"
    r"account\s+messages|important:|days\s+in\s+billing|"
    r"customer\s+service|www\.citi|visit\s+citi|citicards|"
    r"for\s+more\s+information|page\s+\d+\s+of\s+\d+|"
    r"standard\s+purchases?,?\s*cont|"
    r"up\s+to\s+\$[\d,]+\s+per\s+year|then\s+\d+%|"
    r"\btty:|total\s+earned|"
    r"\d{4}\s+totals|"
    r"\bpurchases\s+standard\b|"
    r"\bstandard\s+(?:purch|adv)|"
    r"\bbalances\s+followed\s+by|"
    r"\bdaily\s+balance\s+method|"
    r"\baverage\s+daily\s+balance|"
    r"\bmore\s+than\s+\$\d+\s+in\b|"
    r"\bmay\s+vary\b|"
    r"^\d+%$",                         # standalone percentage (residual from rewards text)
    re.IGNORECASE,
)

# Boilerplate/legal section markers — once we see one of these, stop absorbing lines
_BOILERPLATE_START = re.compile(
    r"\bfees\s+charged\b|\binterest\s+charged\b|"
    r"how\s+we\s+calculate|what\s+to\s+do\s+if|your\s+rights|"
    r"billing\s+inquiries|payment\s+information|credit\s+reporting|"
    r"important\s+information|how\s+to\s+(?:report|avoid)|"
    r"balance\s+transfers?\b|when\s+your\s+payment|"
    r"payment\s+amount\s+automatically|express\s+mail|"
    r"crediting\s+payments|other\s+account|"
    r"\byou\s+must\s+contact\s+us|"
    r"\byou\s+authorize\b|"
    r"©\s*\d{4}|citibank|citigroup|"
    r"payment\s+(?:due|cutoff)|minimum\s+payment|"
    r"if\s+you\s+(?:have\s+questions|think|are\s+dissatisfied)|"
    r"account\s+number|dollar\s+amount|description\s+of\s+problem",
    re.IGNORECASE,
)

# Right-column rewards/summary text that pdfplumber merges with transaction lines
# Patterns like: "Costco1................. +$0.00", "3% on restaurants ... +$46.57",
# "electric vehicle (EV) charging purchases", "worldwide, including gas and EV charging at"
_RIGHT_COLUMN_NOISE = re.compile(
    r"\.{3,}\s*\+?\$[\d,.]+$|"       # ...+$0.00 or ...$46.57 at end of line
    r"\d+%\s+on\s+.+$|"               # "3% on restaurants..." reward descriptions
    r"\d+%\s+and\s+\d+%.*$|"           # "5% And 4% Earn Is On A Combined..."
    r"\band\s+ev\s+charging\b.*$|"     # "And Ev Charging +$2.19"
    r"electric\s+vehicle.*$|"          # EV charging text
    r"worldwide.*$|"                   # "worldwide, including..."
    r"Costco\d*\.{3,}.*$|"            # "Costco1................. +$0.00"
    r"».*$|"                           # "» Visit Citi.com/costco"
    r"visit\s+citi\S*.*$|"             # "Visit Citi.com/costco"
    r"for\s+more\s+information.*$|"    # "For More Information"
    r"customer\s+service.*$|"          # "Customer Service 1-..."
    r"page\s+\d+\s+of\s+\d+.*$|"      # "Page 3 Of 3..."
    r"\btty:.*$|"                      # "tty: 711..."
    r"standard\s+purchases?,?\s*cont.*$|"  # "Standard Purchases, Cont'd"
    r"\d+\s*up\s+to\s+\$.*$|"          # "1up To $7,000 Per Year..."
    r"\btotal\s+costco.*$|"            # "Total Costco" rewards section header
    r"\bcostco\.com.*$|"               # "Costco.com" trailing link
    r"\btotal\s+earned\b.*$|"          # "Total Earned: $91.75 Cardholder Name"
    r"\bpurchases$|"                   # trailing "Purchases" word
    r"\bcash\s+back\s+reward\w*.*$|"   # "cash back rewards" rewards column text
    r"\blast\s+statement\b.*$|"         # "Last Statement +$91.75 Name: ..."
    r"\bname:\s*\S+/\S+.*$|"           # "Name: Surname/givenname ..." account holder
    r"\bname:\s*X{4,}.*$|"             # "Name: Xxxxxxxxxxxxxxxxxxxx ..." masked name
    r"\b[A-Z]aa\s+To\s+[A-Z]ao\b.*$|" # "Xaa To Xao" rewards tier text
    r"\bdepart:\s*\d{2}/\d{2}/\d{2}.*$|"  # "Depart: 03/23/25 Phx To Sea : F9: ..."
    r"\bdepart:\s*00/00/00.*$|"        # "Depart: 00/00/00" masked itinerary
    r"\bclass:\s*\w\s*:.*$|"           # "Class: E : Stop:o" flight class
    r"\bphone\s*number:.*$|"           # "Phone Number: Name: Pickup: ..."
    r"\bpickup:\s*\d{2}/\d{2}/\d{2}.*$|"  # "Pickup: 00/00/00" rental dates
    r"\bspend\s+per\s+year\b.*$|"      # "Spend Per Year, 1% Thereafter"
    r"\b\d+%\s+thereafter\b.*$|"       # "1% Thereafter" rewards tier
    r"\s*\($|"                          # trailing orphan parenthesis
    r"^costco$|"                        # standalone "Costco" (from rewards column residual)
    r"\bpurchases\s+\+\$.*$",           # "purchases +$22.69" rewards earned text
    re.IGNORECASE,
)

# Noise patterns applied to description text after amount extraction
# (these patterns may appear before amounts in raw lines, so can't be in _RIGHT_COLUMN_NOISE)
_DESC_NOISE = re.compile(
    r"www\.citi\S*.*|"                 # "Www.citicards.com Customer Service..."
    r"www\.(?![\w.-]+\.(?:com|org|net)\b)\S+.*|"  # Suspicious www. URLs (not the vendor's own)
    r"\s+\d[\d,.]*\s+(?:canadian\s+dollar|euro|pound)\b.*|"  # "89.25 Canadian Dollar"
    r"\s+costco$",                      # Trailing "Costco" from rewards column
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
        personal_name_noise = _compile_personal_name_noise()

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

            # Description is everything except the amount
            desc_before = all_text[:amount_match.start()].strip()
            desc_after = all_text[amount_match.end():].strip()
            
            # Strip right-column noise from both parts
            desc_before = _RIGHT_COLUMN_NOISE.sub("", desc_before).strip()
            desc_after = _RIGHT_COLUMN_NOISE.sub("", desc_after).strip()

            # If desc_before is just a state code, country code, or mangled state
            # (PAWA, PSWA, WA, CA, US, etc.) with no real merchant info, treat as empty
            if re.match(r"^(?:P[A-Z]?[SW]?WA|[A-Z]{2}|US|USA)$", desc_before, re.IGNORECASE):
                desc_before = ""

            # Strip description-level noise (patterns unsafe for raw-line filtering)
            desc_before = _DESC_NOISE.sub("", desc_before).strip()
            desc_after = _DESC_NOISE.sub("", desc_after).strip()
            if personal_name_noise:
                desc_before = personal_name_noise.sub("", desc_before).strip()
                desc_after = personal_name_noise.sub("", desc_after).strip()

            # Strip summary noise from both parts (truncate at first match)
            noise_match = _SUMMARY_NOISE.search(desc_before)
            if noise_match:
                desc_before = desc_before[:noise_match.start()].strip()
            noise_match = _SUMMARY_NOISE.search(desc_after)
            if noise_match:
                desc_after = desc_after[:noise_match.start()].strip()
            
            # Combine: desc_before is the actual merchant description.
            # desc_after (text after the amount) is almost always right-column
            # noise from two-column PDFs, so only use it as a fallback.
            if desc_before:
                description = desc_before
            elif desc_after:
                description = desc_after
            else:
                description = "(no description)"

            # Safety net: cap description length (no vendor name is 100+ chars)
            if len(description) > 100:
                description = description[:100].rsplit(" ", 1)[0].strip()

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


def _compile_personal_name_noise() -> re.Pattern[str] | None:
    """Build a trailing-noise pattern from optional local cardholder names."""
    names = load_personal_config().cardholder_names
    if not names:
        return None
    alternatives = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    return re.compile(rf"\s+(?:{alternatives})\b.*$", re.IGNORECASE)


def _clean_line(line: str) -> str:
    """Strip right-column rewards/summary noise from a line."""
    cleaned = _RIGHT_COLUMN_NOISE.sub("", line).strip()
    # Second pass: catch residuals left after first strip (e.g., "Costco" from
    # "Costco Cash Back Rewards Balance", "4%" from "4% cash back rewards...")
    if cleaned:
        cleaned = _RIGHT_COLUMN_NOISE.sub("", cleaned).strip()
    return cleaned


def _group_into_blocks(lines: list[str]) -> list[list[str]]:
    """Group lines into transaction blocks.

    A new block starts when a line begins with a date pattern (MM/DD).
    Continuation lines are appended to the current block.
    When a date line has no description text (just date + amount), the last
    line of the previous block is moved to the new block as the description.
    This handles two-column PDF layouts where descriptions precede their dates.
    """
    blocks: list[list[str]] = []
    current_block: list[str] = []
    in_boilerplate = False
    seen_transaction = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Only check for boilerplate after we've seen at least one transaction
        if seen_transaction and _BOILERPLATE_START.search(stripped):
            in_boilerplate = True
        if in_boilerplate:
            continue

        if _is_section_header(stripped):
            continue

        cleaned = _clean_line(stripped)
        if not cleaned:
            continue

        is_date_line = bool(_DATE_START.match(cleaned))

        if is_date_line:
            seen_transaction = True
            # Check if this date line has description text or just date + amount
            date_match = _DATE_START.match(cleaned)
            remaining = cleaned[date_match.end():].strip() if date_match else ""
            # Extract just the text part (before $amount) to check for real desc
            desc_part = re.split(r"\s*-?\$", remaining)[0].strip() if remaining else ""
            # Strip a potential second date (posting date) from desc_part
            desc_part = re.sub(r"^\d{1,2}/\d{1,2}\s*", "", desc_part).strip()
            # Standalone state codes, country codes, or mangled states aren't real descriptions
            has_desc = bool(desc_part) and not re.match(
                r"^(?:P[A-Z]?[SW]?WA|[A-Z]{2})$", desc_part, re.IGNORECASE
            )

            if not has_desc and current_block and len(current_block) > 1:
                # The last line of the previous block is likely THIS transaction's
                # description — but only steal it if it looks like a merchant name
                # (not a short location suffix like "PAWA" or "WA")
                candidate = current_block[-1]
                if len(candidate) > 6 and not re.match(r"^[A-Z]{2,5}$", candidate):
                    stolen_desc = current_block.pop()
                    blocks.append(current_block)
                    current_block = [cleaned, stolen_desc]
                else:
                    if current_block:
                        blocks.append(current_block)
                    current_block = [cleaned]
            else:
                if current_block:
                    blocks.append(current_block)
                current_block = [cleaned]
        elif current_block and not _SUMMARY_NOISE.search(cleaned):
            # Limit continuation lines to prevent runaway noise absorption
            continuation_count = len(current_block) - 1  # first line is the date line
            if continuation_count < 3:
                # Reject orphan name-like continuation lines (cardholder names etc.)
                # when the block already has description text — either inline
                # or from a previous continuation/steal.
                date_line = current_block[0]
                has_desc_in_block = bool(re.search(
                    r"\d{2}/\d{2}(?:\s+\d{2}/\d{2})?\s+(?!\d{2}/\d{2})[A-Za-z]",
                    date_line,
                )) or len(current_block) > 1  # stolen desc or prior continuation
                is_name_like = bool(re.match(
                    r"^[A-Za-z]+(?:\s+[A-Za-z]\.?)?(?:\s+[A-Za-z]+){1,2}$",
                    cleaned,
                )) and len(cleaned) > 10
                if is_name_like and has_desc_in_block:
                    pass  # skip orphan name-like lines after complete descriptions
                else:
                    current_block.append(cleaned)

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
        normalized_vendor=normalize_vendor(description),
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
