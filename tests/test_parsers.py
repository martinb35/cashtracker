"""Tests for generic CSV normalizer."""

from datetime import date
from decimal import Decimal

from cashtracker.parsers.generic_csv import GenericCSVNormalizer


class TestGenericCSVNormalizer:
    def setup_method(self):
        self.normalizer = GenericCSVNormalizer()

    def test_can_handle_standard_headers(self):
        rows = [{"Date": "01/15/2024", "Amount": "-45.67", "Description": "STORE"}]
        assert self.normalizer.can_handle(rows) == 0.5

    def test_can_handle_no_description(self):
        rows = [{"Date": "01/15/2024", "Amount": "-45.67"}]
        assert self.normalizer.can_handle(rows) == 0.3

    def test_cannot_handle_empty(self):
        assert self.normalizer.can_handle([]) == 0.0

    def test_cannot_handle_no_date(self):
        rows = [{"Name": "Something", "Value": "100"}]
        assert self.normalizer.can_handle(rows) == 0.0

    def test_normalize_basic(self):
        rows = [
            {"Date": "01/15/2024", "Amount": "-45.67", "Description": "WHOLE FOODS"},
            {"Date": "01/16/2024", "Amount": "-15.99", "Description": "NETFLIX"},
        ]
        result = self.normalizer.normalize(rows, source_file="test.csv")
        assert len(result.transactions) == 2
        assert result.transactions[0].transaction_date == date(2024, 1, 15)
        assert result.transactions[0].amount == Decimal("-45.67")
        assert result.transactions[0].raw_description == "WHOLE FOODS"

    def test_normalize_debit_credit_columns(self):
        rows = [
            {"Date": "01/15/2024", "Debit": "45.67", "Credit": "", "Description": "STORE"},
            {"Date": "01/16/2024", "Debit": "", "Credit": "100.00", "Description": "DEPOSIT"},
        ]
        result = self.normalizer.normalize(rows)
        assert result.transactions[0].amount == Decimal("-45.67")
        assert result.transactions[1].amount == Decimal("100.00")

    def test_normalize_parenthetical_negatives(self):
        rows = [{"Date": "01/15/2024", "Amount": "(45.67)", "Description": "STORE"}]
        result = self.normalizer.normalize(rows)
        assert result.transactions[0].amount == Decimal("-45.67")

    def test_normalize_dollar_sign(self):
        rows = [{"Date": "01/15/2024", "Amount": "$45.67", "Description": "STORE"}]
        result = self.normalizer.normalize(rows)
        assert result.transactions[0].amount == Decimal("45.67")

    def test_normalize_iso_date(self):
        rows = [{"Date": "2024-01-15", "Amount": "10", "Description": "TEST"}]
        result = self.normalizer.normalize(rows)
        assert result.transactions[0].transaction_date == date(2024, 1, 15)

    def test_bad_date_produces_warning(self):
        rows = [{"Date": "not-a-date", "Amount": "10", "Description": "TEST"}]
        result = self.normalizer.normalize(rows)
        assert len(result.transactions) == 0
        assert any("could not parse date" in w for w in result.warnings)

    def test_bad_amount_produces_warning(self):
        rows = [{"Date": "01/15/2024", "Amount": "not-a-number", "Description": "TEST"}]
        result = self.normalizer.normalize(rows)
        assert len(result.transactions) == 0
        assert any("could not parse amount" in w for w in result.warnings)

    def test_transaction_header_variants(self):
        rows = [{"Transaction Date": "01/15/2024", "Transaction Amount": "-10", "Memo": "TEST"}]
        result = self.normalizer.normalize(rows)
        assert len(result.transactions) == 1
