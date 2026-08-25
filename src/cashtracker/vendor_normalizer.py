"""Vendor name normalizer — cleans raw transaction descriptions into readable names."""

from __future__ import annotations

import re

# Payment processor prefixes: "SQ *", "SP ", "TST*", "FSP*", "PP*", "PAYPAL *", etc.
_PROCESSOR_PREFIX = re.compile(
    r"^(?:SQ\s*\*|SP\s+|TST\s*\*|FSP\s*\*|PP\s*\*|PAYPAL\s*\*|APL\s*\*|"
    r"CKE\s*\*|CHK\s*\*|INT\s*\*|DD\s*\*|DOORDASH\s*\*|UBER\s*\*\s*)\s*",
    re.IGNORECASE,
)

# APPLE.COM/XX pattern — keep "Apple" as the vendor name
_APPLE_COM = re.compile(r"^APPLE\.COM/\w+\b", re.IGNORECASE)

# Store/location number: #03801, # 1234
_STORE_NUMBER = re.compile(r"\s*#\s*\d+")

# Phone numbers: 425-803-0222, 800.555.1234, (425)803-0222, 1-800-555-1234
# Also matches reference-like digit strings with dashes: 186-65234486
_PHONE_NUMBER = re.compile(
    r"\s*(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]\d{4}|\d{1,3}-\d{5,}|\d{10,})"
)

# US state codes at end (actual 2-letter USPS codes, not arbitrary letter pairs)
_US_STATES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|"
    "MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|"
    "SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC|PR|VI|GU|AS|MP"
)
_TRAILING_STATE = re.compile(rf"\s+(?:{_US_STATES})$", re.IGNORECASE)

# City + state at end: "REDMOND WA", "WOODINVILLE WA"
# Only match a single word (6+ chars to avoid eating short vendor words) before the state
_CITY_STATE = re.compile(
    rf"\s+[A-Z][A-Za-z]{{5,}}\s+(?:{_US_STATES})$", re.IGNORECASE
)

# Mangled state codes from two-column PDF layouts: "SNOQUALMIE PAWA", "SNOQUALMIE PSWA", "F&B"
# Include the preceding city name since the state code was mangled with it
_MANGLED_STATE = re.compile(r"\s+[A-Z][A-Za-z]{3,}\s+P[A-Z]?[SW]?WA$|\s+F&B\b", re.IGNORECASE)

# Trailing country code: "US", "USA", "IT" (Italy), etc.
_TRAILING_COUNTRY = re.compile(r"\s+(?:US|USA|CA|CAN|GB|UK|IT|FR|DE|ES|AU|NZ|JP|MX)$", re.IGNORECASE)

# Trailing numeric-only tokens (ZIP codes, reference numbers, long digit strings)
_TRAILING_NUMBERS = re.compile(r"\s+\d{5,}$")

# Trailing transaction IDs / reference numbers that are mostly digits
_TRAILING_REF = re.compile(r"\s+\d[\d-]{6,}$")

# Long digit strings merged with following text by pdfplumber:
# "1254249356344WWW.BRITISHAINY" → strip the digit blob and whatever follows
# Also catches digit-dash reference numbers: "1252216654839034-44930787"
_DIGIT_BLOB = re.compile(r"\s+\d{10,}[\d-]*\S*")

# Trailing punctuation/separators: "Salt & Straw -", "Doppio Redmond Wa (", "Elmer's - Tacoma,"
_TRAILING_PUNCT = re.compile(r"\s*[-–—(,]+$")

# Broken URLs from PDF whitespace: "Www Costco Com", "WWW COSTCO COM 800-955-2292 WA"
# Also handles dotted URLs: "WWW.DOXA-CHURCH.COM"
_URL_PATTERN = re.compile(
    r"\bwww[\s.]+\S+[\s.]+(?:com|org|net)\b.*|"
    r"\bwww\.\S+\.(?:com|org|net)\b",
    re.IGNORECASE,
)

# Credit card statement noise that leaks into descriptions
_STATEMENT_NOISE = re.compile(
    r"\s*\btotal\s+costco.*$|"
    r"\s*\bcostco\.com.*$|"
    r"\s*\btotal\s+earned\b.*$|"
    r"\s*\bpurchases$",
    re.IGNORECASE,
)

# Trailing URL fragments merged by pdfplumber: "Estagosq.com", "Foodtmaple"
_TRAILING_URL_FRAGMENT = re.compile(r"\S*\w\.(?:com|org|net)\b.*$", re.IGNORECASE)

# Multiple spaces
_MULTI_SPACE = re.compile(r"\s{2,}")

# Asterisks used as separators
_ASTERISK_SEP = re.compile(r"\s*\*\s*")

# Known vendor corrections for pdfplumber-merged text that can't be parsed algorithmically.
# Keys are lowercased substrings to match; values are the corrected vendor names.
_VENDOR_CORRECTIONS = {
    "british a": "British Airways",
    "hawaiian ai": "Hawaiian Airlines",
    "alaska air": "Alaska Air",     # keep as-is but prevent further truncation
    "delta air": "Delta Air Lines",
    "frontier ai": "Frontier Airlines",
    "parknjetseatawa": "Park N Jet",
    "cascadiapizzaco": "Cascadia Pizza Co",
    "bestbuycom": "Best Buy",
    "help.uber.com": "Uber",
    "booking.cnl": "Booking.com",
    "in-n-outphx": "In-N-Out",
}

# Patterns for merged store#/city text: "353redmond", "888bestbuy"
_MERGED_NUM_CITY = re.compile(r"\s+\d{2,4}[a-z]\w*", re.IGNORECASE)


def normalize_vendor(raw: str) -> str:
    """Clean a raw transaction description into a human-readable vendor name.

    Examples:
        "CHICK-FIL-A #03801 425-803-0222 WA" → "Chick-Fil-A"
        "FSP*POSTDOC BREWING REDMOND WA"      → "Postdoc Brewing"
        "SP LADY YUM 186-65234486 WA"         → "Lady Yum"
        "WHOLEFDS MKT 10234"                  → "Wholefds Mkt"
        "COSTCO WHSE #1234 ISSAQUAH WA"       → "Costco Whse"
    """
    text = raw.strip()
    if not text:
        return ""

    # Strip payment processor prefixes
    text = _PROCESSOR_PREFIX.sub("", text)

    # Handle APPLE.COM/XX → "Apple"
    if _APPLE_COM.match(text):
        text = "Apple"
        return text

    # Strip credit card statement noise (before location stripping)
    text = _STATEMENT_NOISE.sub("", text).strip()

    # Strip trailing URL fragments merged by pdfplumber (e.g., "Estagosq.com")
    url_frag_match = _TRAILING_URL_FRAGMENT.search(text)
    if url_frag_match:
        prefix = text[:url_frag_match.start()].strip()
        if prefix:
            text = prefix

    # Remove store numbers
    text = _STORE_NUMBER.sub("", text)

    # Remove long digit blobs merged with trailing text (e.g., "1254249356344WWW.BRITISHAINY")
    # Must run before phone number stripping which would consume just the digits
    text = _DIGIT_BLOB.sub("", text).strip()

    # Remove phone numbers
    text = _PHONE_NUMBER.sub("", text)

    # Remove trailing reference/transaction IDs
    text = _TRAILING_REF.sub("", text)
    text = _TRAILING_NUMBERS.sub("", text)

    # Remove city + state first (more specific pattern)
    text = _CITY_STATE.sub("", text)

    # Remove trailing country code
    text = _TRAILING_COUNTRY.sub("", text)

    # Remove mangled state codes from PDF layout
    text = _MANGLED_STATE.sub("", text)

    # If that didn't match, try just trailing state code
    text = _TRAILING_STATE.sub("", text)

    # Remove duplicate trailing city/location name — single or multi-word
    # Handles: "SUMMIT AT SNOQUALMIE SNOQUALMIE", "In-N-Out La Quinta La Quinta",
    #          "Cle Elum Pizza Co Cle Elum", "Hotel Wolkenstein Gmbh Wolkenstein",
    #          "Netflix.com Netflix.com"
    words = text.split()
    if len(words) == 2 and words[0].upper() == words[1].upper():
        words = words[:1]
        text = words[0]
    else:
        for n_words in (2, 1):  # try 2-word then 1-word dedup
            if len(words) >= n_words * 2 + 1:
                tail = " ".join(words[-n_words:]).upper()
                # Check adjacent match first
                prev = " ".join(words[-n_words * 2:-n_words]).upper()
                if tail == prev:
                    words = words[:-n_words]
                    text = " ".join(words)
                    break
                # Check non-adjacent: if last word(s) appear earlier in the string
                if n_words == 1 and any(w.upper() == tail for w in words[:-1]):
                    words = words[:-1]
                    text = " ".join(words)
                    break

    # Handle broken URLs: extract the domain name as the vendor
    url_match = _URL_PATTERN.search(text)
    if url_match:
        prefix = text[:url_match.start()].strip()
        # Extract the middle part as the vendor name (e.g., "COSTCO" from "WWW COSTCO COM")
        url_text = url_match.group(0)
        parts = re.split(r"[\s.]+", url_text)
        # Parts like ["WWW", "COSTCO", "COM", ...] — take the non-www/com/org/net parts
        domain_parts = [p for p in parts if p.upper() not in ("WWW", "COM", "ORG", "NET", "")]
        domain_name = " ".join(domain_parts) if domain_parts else ""
        # If there's text before the URL, prefer it (the URL is likely noise)
        if prefix:
            text = prefix
        elif domain_name:
            text = domain_name
        else:
            text = ""

    # Clean up asterisk separators remaining after prefix removal
    text = _ASTERISK_SEP.sub(" ", text)

    # Collapse whitespace and strip
    text = _MULTI_SPACE.sub(" ", text).strip()

    # Remove trailing punctuation/dashes
    text = _TRAILING_PUNCT.sub("", text).strip()

    # Strip merged store#/city text: "Paris Baguette - 353redmond" → "Paris Baguette"
    text = _MERGED_NUM_CITY.sub("", text).strip()
    text = _TRAILING_PUNCT.sub("", text).strip()

    # Apply known vendor corrections for pdfplumber artifacts
    text_lower = text.lower()
    for pattern, correction in _VENDOR_CORRECTIONS.items():
        if pattern in text_lower:
            return correction

    # Title-case the result
    text = _title_case(text)

    # Final guard: if the entire result is just a state code, country code,
    # or mangled state, it's not a real vendor name
    if re.match(
        r"^(?:[A-Z]{2}|US|USA|P[A-Z]?[SW]?WA)$", text, re.IGNORECASE
    ):
        return ""

    return text


def _title_case(text: str) -> str:
    """Smart title case that preserves hyphenated words.

    "CHICK-FIL-A" → "Chick-Fil-A"
    "PLAY IT AGAIN SPORTS" → "Play It Again Sports"
    """
    words = text.split()
    result = []
    for word in words:
        if "-" in word:
            result.append("-".join(part.capitalize() for part in word.split("-")))
        else:
            result.append(word.capitalize())
    return " ".join(result)
