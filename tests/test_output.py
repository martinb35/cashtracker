"""Tests for CSV output."""

import csv
import io
from datetime import date
from decimal import Decimal

from cashtracker.models import Transaction
from cashtracker.output import write_csv


class TestWriteCSV:
    def test_output_format(self):
        txns = [
            Transaction(
                transaction_date=date(2024, 1, 15),
                raw_description="WHOLE FOODS MKT",
                amount=Decimal("-45.67"),
                category="groceries",
                normalized_vendor="Whole Foods",
            ),
        ]
        output = write_csv(txns)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["date"] == "2024-01-15"
        assert rows[0]["category"] == "groceries"
        assert rows[0]["amount"] == "-45.67"
        assert rows[0]["vendor/company/item"] == "Whole Foods"

    def test_output_columns(self):
        output = write_csv([])
        lines = output.strip().split("\n")
        assert lines[0] == "date,category,amount,vendor/company/item"

    def test_writes_to_file(self, tmp_path):
        txn = Transaction(
            transaction_date=date(2024, 1, 1),
            raw_description="TEST",
            amount=Decimal("10"),
            category="income",
        )
        path = tmp_path / "out.csv"
        result = write_csv([txn], path)
        assert path.exists()
        assert result == str(path)
        content = path.read_text()
        assert "income" in content

    def test_vendor_fallback_to_raw(self):
        txn = Transaction(
            transaction_date=date(2024, 1, 1),
            raw_description="RAW DESC",
            amount=Decimal("10"),
        )
        output = write_csv([txn])
        assert "RAW DESC" in output
