"""Tests for the categorizer."""

from datetime import date
from decimal import Decimal

from cashtracker.categorizer import _match_keywords, _parse_response, categorize_transactions
from cashtracker.config import Config
from cashtracker.models import Transaction


class TestMatchKeywords:
    def test_match_found(self):
        categories = {"groceries": ["whole foods", "grocery"], "dining": ["restaurant"]}
        assert _match_keywords("WHOLE FOODS MARKET #123", categories) == "groceries"

    def test_no_match(self):
        categories = {"groceries": ["whole foods"], "dining": ["restaurant"]}
        assert _match_keywords("MYSTERIOUS VENDOR XYZ", categories) is None

    def test_case_insensitive(self):
        categories = {"dining": ["starbucks"]}
        assert _match_keywords("STARBUCKS COFFEE", categories) == "dining"

    def test_skips_uncategorized(self):
        categories = {"uncategorized": ["something"], "dining": ["cafe"]}
        assert _match_keywords("something cafe", categories) == "dining"


class TestParseResponse:
    def test_valid_json(self):
        result = _parse_response('["groceries", "dining"]', ["groceries", "dining"])
        assert result == ["groceries", "dining"]

    def test_invalid_category_becomes_uncategorized(self):
        result = _parse_response('["groceries", "invalid_cat"]', ["groceries", "dining"])
        assert result == ["groceries", "uncategorized"]

    def test_json_with_surrounding_text(self):
        result = _parse_response('Here are the results:\n["groceries"]\nDone!', ["groceries"])
        assert result == ["groceries"]

    def test_not_json_returns_empty(self):
        result = _parse_response("just some text", ["groceries"])
        assert result == []

    def test_case_insensitive_matching(self):
        result = _parse_response('["Groceries"]', ["groceries"])
        assert result == ["groceries"]


class TestCategorizeTransactions:
    def test_keyword_match(self, sample_transactions):
        cfg = Config()
        categorize_transactions(sample_transactions, cfg, use_ai=False)

        assert sample_transactions[0].category == "groceries"  # WHOLE FOODS
        assert sample_transactions[0].confidence == 1.0
        assert sample_transactions[1].category == "entertainment"  # NETFLIX
        assert sample_transactions[2].category == "income"  # PAYROLL
        assert sample_transactions[3].category == "uncategorized"  # MYSTERIOUS VENDOR

    def test_no_ai_leaves_unmatched(self, sample_transactions):
        cfg = Config()
        categorize_transactions(sample_transactions, cfg, use_ai=False)
        assert sample_transactions[3].category == "uncategorized"
        assert sample_transactions[3].confidence == 0.0
