"""PDF file reader — extracts tables and text from text-based PDFs."""

from __future__ import annotations

import re
from pathlib import Path

import pdfplumber


class ScannedPDFError(Exception):
    """Raised when a PDF appears to be scanned/image-based."""


def read_pdf(path: Path) -> list[dict[str, str]]:
    """Extract data from a text-based PDF.

    Tries table extraction first. If that fails or produces unusable headers,
    falls back to text-line extraction.
    Raises ScannedPDFError if the PDF appears to be image-based.
    """
    all_text_lines: list[str] = []
    all_table_rows: list[list[str]] = []
    pages_with_content = 0

    with pdfplumber.open(path) as pdf:
        if not pdf.pages:
            raise ValueError(f"PDF has no pages: {path}")

        for page in pdf.pages:
            text = page.extract_text()
            has_text = text and len(text.strip()) >= 20

            if has_text:
                pages_with_content += 1
                all_text_lines.extend(text.strip().splitlines())

            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row and any(cell and cell.strip() for cell in row):
                        pages_with_content += 1
                        all_table_rows.append([cell.strip() if cell else "" for cell in row])

    if pages_with_content == 0:
        raise ScannedPDFError(
            f"{path} appears to be scanned or image-based. "
            "CashTracker v1 only supports text-based PDFs. "
            "Try exporting your statement as CSV from your bank's website."
        )

    # Try table extraction first
    if all_table_rows:
        result = _rows_to_dicts(all_table_rows)
        if result and _has_usable_headers(result):
            return result

    # Fall back to text-line extraction
    if all_text_lines:
        return [{"_raw_line": line, "_format": "text_lines"} for line in all_text_lines if line.strip()]

    raise ValueError(
        f"No data found in {path}. "
        "The PDF may not contain extractable text or tables."
    )


def _rows_to_dicts(rows: list[list[str]]) -> list[dict[str, str]]:
    """Convert raw table rows to dicts using the first row as headers."""
    if len(rows) < 2:
        return []

    headers = [h.lower().replace("\n", " ") for h in rows[0]]
    result = []
    for row in rows[1:]:
        padded = row + [""] * (len(headers) - len(row))
        result.append(dict(zip(headers, padded[: len(headers)])))
    return result


def _has_usable_headers(rows: list[dict[str, str]]) -> bool:
    """Check if extracted table has recognizable financial headers."""
    if not rows:
        return False
    headers = {h.lower() for h in rows[0].keys()}
    financial_terms = {"date", "amount", "description", "debit", "credit", "transaction", "posting", "memo", "payee"}
    # Require at least one header that IS a financial term or starts/ends with one
    # (avoids false positives like "year-to-date" matching "date")
    for header in headers:
        words = re.split(r"[\s,;]+", header)
        if any(word in financial_terms for word in words):
            return True
    return False
