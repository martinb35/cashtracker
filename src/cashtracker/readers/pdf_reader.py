"""PDF file reader — extracts tables and text from text-based PDFs."""

from __future__ import annotations

from pathlib import Path

import pdfplumber


class ScannedPDFError(Exception):
    """Raised when a PDF appears to be scanned/image-based."""


def read_pdf(path: Path) -> list[dict[str, str]]:
    """Extract tabular data from a text-based PDF.

    Returns rows as a list of dicts (header row becomes keys).
    Raises ScannedPDFError if the PDF appears to be image-based.
    """
    all_rows: list[list[str]] = []

    with pdfplumber.open(path) as pdf:
        if not pdf.pages:
            raise ValueError(f"PDF has no pages: {path}")

        for page in pdf.pages:
            text = page.extract_text()
            if not text or len(text.strip()) < 20:
                # Page has very little text — likely scanned
                tables = page.extract_tables()
                if not tables:
                    raise ScannedPDFError(
                        f"Page {page.page_number} in {path} appears to be scanned or image-based. "
                        "CashTracker v1 only supports text-based PDFs. "
                        "Try exporting your statement as CSV from your bank's website."
                    )

            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row and any(cell and cell.strip() for cell in row):
                        all_rows.append([cell.strip() if cell else "" for cell in row])

    if not all_rows:
        raise ValueError(
            f"No tabular data found in {path}. "
            "The PDF may not contain a table, or the format is not supported."
        )

    return _rows_to_dicts(all_rows)


def _rows_to_dicts(rows: list[list[str]]) -> list[dict[str, str]]:
    """Convert raw table rows to dicts using the first row as headers."""
    if len(rows) < 2:
        return []

    headers = [h.lower().replace("\n", " ") for h in rows[0]]
    result = []
    for row in rows[1:]:
        # Pad row if shorter than headers
        padded = row + [""] * (len(headers) - len(row))
        result.append(dict(zip(headers, padded[: len(headers)])))
    return result
