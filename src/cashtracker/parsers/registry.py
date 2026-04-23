"""Parser registry — selects the best normalizer for a given statement."""

from __future__ import annotations

from typing import Any

from cashtracker.models import ParsedStatement
from cashtracker.parsers.base import StatementNormalizer
from cashtracker.parsers.generic_csv import GenericCSVNormalizer

# Built-in normalizers (institution-specific ones can be added here)
_NORMALIZERS: list[StatementNormalizer] = [
    GenericCSVNormalizer(),
]


def register_normalizer(normalizer: StatementNormalizer) -> None:
    """Register a custom normalizer."""
    _NORMALIZERS.append(normalizer)


def detect_and_parse(
    raw_data: list[dict[str, str]],
    source_file: str = "",
    metadata: dict[str, Any] | None = None,
) -> ParsedStatement:
    """Detect the best normalizer and parse the statement.

    Scores all registered normalizers and uses the one with the highest
    confidence. Falls back to GenericCSVNormalizer.
    """
    if not raw_data:
        return ParsedStatement(
            source_file=source_file,
            warnings=["No data to parse"],
        )

    best_normalizer: StatementNormalizer | None = None
    best_score = 0.0

    for normalizer in _NORMALIZERS:
        score = normalizer.can_handle(raw_data, metadata)
        if score > best_score:
            best_score = score
            best_normalizer = normalizer

    if best_normalizer is None or best_score == 0.0:
        return ParsedStatement(
            source_file=source_file,
            warnings=[
                "No normalizer could handle this statement format. "
                "Check that the file has recognizable column headers (date, amount, description)."
            ],
        )

    return best_normalizer.normalize(raw_data, source_file)
