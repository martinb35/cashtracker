"""Shared test fixtures."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest


@pytest.fixture
def tmp_csv(tmp_path: Path):
    """Factory fixture to create temporary CSV files."""

    def _make(rows: list[dict[str, str]], filename: str = "test.csv") -> Path:
        path = tmp_path / filename
        if not rows:
            path.write_text("")
            return path

        fieldnames = list(rows[0].keys())
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        path.write_text(buf.getvalue(), encoding="utf-8")
        return path

    return _make


@pytest.fixture
def sample_transactions():
    """Create a list of sample transactions for testing."""
    from datetime import date
    from decimal import Decimal

    from cashtracker.models import Transaction

    return [
        Transaction(
            transaction_date=date(2024, 1, 15),
            raw_description="WHOLE FOODS MARKET #123",
            amount=Decimal("-45.67"),
        ),
        Transaction(
            transaction_date=date(2024, 1, 16),
            raw_description="NETFLIX.COM",
            amount=Decimal("-15.99"),
        ),
        Transaction(
            transaction_date=date(2024, 1, 17),
            raw_description="PAYROLL DEPOSIT",
            amount=Decimal("3500.00"),
        ),
        Transaction(
            transaction_date=date(2024, 1, 18),
            raw_description="MYSTERIOUS VENDOR XYZ",
            amount=Decimal("-29.99"),
        ),
    ]
