"""Abstract base class for statement normalizers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from cashtracker.models import ParsedStatement


class StatementNormalizer(ABC):
    """Base class for institution-specific statement normalizers.

    Subclasses implement `can_handle` to indicate whether they recognize
    a particular statement format, and `normalize` to convert raw data
    into a ParsedStatement.
    """

    @abstractmethod
    def can_handle(self, raw_data: list[dict[str, str]], metadata: dict[str, Any] | None = None) -> float:
        """Return a confidence score (0.0–1.0) for handling this data.

        Args:
            raw_data: Rows extracted by a file reader.
            metadata: Optional hints (filename, detected institution, etc.)

        Returns:
            0.0 if this normalizer cannot handle the data,
            up to 1.0 for a confident match.
        """

    @abstractmethod
    def normalize(self, raw_data: list[dict[str, str]], source_file: str = "") -> ParsedStatement:
        """Convert raw rows into a ParsedStatement.

        Args:
            raw_data: Rows extracted by a file reader.
            source_file: Path to the original file.

        Returns:
            A ParsedStatement with transactions and metadata.
        """
