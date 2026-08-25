"""Tests for core data models."""

from datetime import date
from decimal import Decimal

from cashtracker.models import ParsedStatement, StatementMetadata, Transaction


class TestTransaction:
    def test_create_minimal(self):
        txn = Transaction(
            transaction_date=date(2024, 1, 15),
            raw_description="WHOLE FOODS",
            amount=Decimal("-45.67"),
        )
        assert txn.transaction_date == date(2024, 1, 15)
        assert txn.amount == Decimal("-45.67")
        assert txn.category == "uncategorized"
        assert txn.confidence == 0.0

    def test_vendor_display_uses_normalized(self):
        txn = Transaction(
            transaction_date=date(2024, 1, 15),
            raw_description="WHOLE FOODS MKT #10234",
            amount=Decimal("-45.67"),
            normalized_vendor="Whole Foods",
        )
        assert txn.vendor_display == "Whole Foods"

    def test_vendor_display_falls_back_to_raw(self):
        txn = Transaction(
            transaction_date=date(2024, 1, 15),
            raw_description="WHOLE FOODS MKT #10234",
            amount=Decimal("-45.67"),
        )
        assert txn.vendor_display == "WHOLE FOODS MKT #10234"

    def test_defaults(self):
        txn = Transaction(
            transaction_date=date(2024, 1, 1),
            raw_description="TEST",
            amount=Decimal("0"),
        )
        assert txn.currency == "USD"
        assert txn.source_file == ""
        assert txn.posted_date is None


class TestParsedStatement:
    def test_empty_statement(self):
        stmt = ParsedStatement()
        assert stmt.transactions == []
        assert stmt.warnings == []
        assert stmt.source_file == ""

    def test_with_transactions(self):
        txn = Transaction(
            transaction_date=date(2024, 1, 1),
            raw_description="TEST",
            amount=Decimal("10"),
        )
        stmt = ParsedStatement(transactions=[txn], source_file="test.csv")
        assert len(stmt.transactions) == 1
        assert stmt.source_file == "test.csv"

    def test_metadata(self):
        meta = StatementMetadata(institution="Chase", account_name="Checking")
        stmt = ParsedStatement(metadata=meta)
        assert stmt.metadata.institution == "Chase"
