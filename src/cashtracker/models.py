"""Core data models for CashTracker."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass
class Transaction:
    """A single financial transaction."""

    transaction_date: date
    raw_description: str
    amount: Decimal
    normalized_vendor: str = ""
    posted_date: Optional[date] = None
    currency: str = "USD"
    source_file: str = ""
    account_name: str = ""
    category: str = "uncategorized"
    confidence: float = 0.0

    @property
    def vendor_display(self) -> str:
        return self.normalized_vendor or self.raw_description


@dataclass
class StatementMetadata:
    """Metadata extracted from a statement."""

    institution: str = ""
    account_name: str = ""
    statement_period_start: Optional[date] = None
    statement_period_end: Optional[date] = None


@dataclass
class ParsedStatement:
    """Result of parsing a statement file."""

    transactions: list[Transaction] = field(default_factory=list)
    metadata: StatementMetadata = field(default_factory=StatementMetadata)
    warnings: list[str] = field(default_factory=list)
    source_file: str = ""
