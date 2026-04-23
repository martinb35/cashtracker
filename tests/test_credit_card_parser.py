"""Tests for credit card text normalizer."""

from datetime import date
from decimal import Decimal

from cashtracker.parsers.credit_card_text import CreditCardTextNormalizer


def _make_lines(lines: list[str]) -> list[dict[str, str]]:
    return [{"_raw_line": line, "_format": "text_lines"} for line in lines]


class TestCreditCardTextNormalizer:
    def setup_method(self):
        self.normalizer = CreditCardTextNormalizer()

    def test_can_handle_text_lines(self):
        data = _make_lines([
            "January 2024 Statement",
            "ACCOUNT SUMMARY",
            "12/19 12/19 CHICK-FIL-A #03801 $13.48",
            "12/19 12/19 SP LADY YUM $58.60",
            "12/20 12/20 FSP*POSTDOC BREWING $69.69",
        ])
        assert self.normalizer.can_handle(data) >= 0.4

    def test_cannot_handle_csv_rows(self):
        data = [{"Date": "01/15/2024", "Amount": "10", "Description": "TEST"}]
        assert self.normalizer.can_handle(data) == 0.0

    def test_cannot_handle_empty(self):
        assert self.normalizer.can_handle([]) == 0.0

    def test_normalize_with_post_date(self):
        data = _make_lines([
            "January 2024 Statement",
            "12/19 12/19 CHICK-FIL-A #03801 $13.48",
        ])
        result = self.normalizer.normalize(data)
        assert len(result.transactions) == 1
        txn = result.transactions[0]
        assert txn.transaction_date == date(2024, 12, 19)
        assert txn.posted_date == date(2024, 12, 19)
        assert "CHICK-FIL-A" in txn.raw_description
        assert txn.amount == Decimal("13.48")

    def test_normalize_payment_negative(self):
        data = _make_lines([
            "January 2024 Statement",
            "01/13 PAYMENT THANK YOU -$609.87",
        ])
        result = self.normalizer.normalize(data)
        assert len(result.transactions) == 1
        txn = result.transactions[0]
        assert txn.amount == Decimal("-609.87")
        assert txn.posted_date is None

    def test_skips_section_headers(self):
        data = _make_lines([
            "January 2024 Statement",
            "ACCOUNT SUMMARY",
            "Payments, Credits and Adjustments",
            "01/13 PAYMENT THANK YOU -$609.87",
            "Standard Purchases",
            "12/19 12/19 CHICK-FIL-A #03801 $13.48",
        ])
        result = self.normalizer.normalize(data)
        assert len(result.transactions) == 2

    def test_detects_year_from_header(self):
        data = _make_lines([
            "Statement Period: December 2025",
            "12/19 12/19 STORE $10.00",
        ])
        result = self.normalizer.normalize(data)
        assert result.transactions[0].transaction_date.year == 2025

    def test_multiple_transactions(self):
        data = _make_lines([
            "January 2024 Statement",
            "12/19 12/19 CHICK-FIL-A #03801 $13.48",
            "12/19 12/19 SP LADY YUM $58.60",
            "12/19 12/19 PLAY IT AGAIN SPORTS $56.89",
            "12/20 12/20 FSP*POSTDOC BREWING $69.69",
        ])
        result = self.normalizer.normalize(data)
        assert len(result.transactions) == 4
        assert result.transactions[3].amount == Decimal("69.69")

    def test_multiline_transaction(self):
        """Transaction where description wraps to next line with the amount."""
        data = _make_lines([
            "January 2024 Statement",
            "12/29 12/29 PIE FOR THE PEOPLE NW    SNOQUALMIE",
            " PAWA $63.35",
        ])
        result = self.normalizer.normalize(data)
        assert len(result.transactions) == 1
        txn = result.transactions[0]
        assert txn.transaction_date == date(2024, 12, 29)
        assert "PIE FOR THE PEOPLE" in txn.raw_description
        assert "PAWA" in txn.raw_description
        assert txn.amount == Decimal("63.35")

    def test_multiline_mixed_with_single(self):
        """Mix of single-line and multi-line transactions."""
        data = _make_lines([
            "January 2024 Statement",
            "12/19 12/19 CHICK-FIL-A #03801 $13.48",
            "12/29 12/29 PIE FOR THE PEOPLE NW    SNOQUALMIE",
            " PAWA $63.35",
            "12/30 12/30 STARBUCKS STORE $5.50",
        ])
        result = self.normalizer.normalize(data)
        assert len(result.transactions) == 3
        assert result.transactions[0].amount == Decimal("13.48")
        assert "PIE FOR THE PEOPLE" in result.transactions[1].raw_description
        assert result.transactions[1].amount == Decimal("63.35")
        assert result.transactions[2].amount == Decimal("5.50")
