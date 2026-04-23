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
        result = categorize_transactions(sample_transactions, cfg, use_ai=False)

        assert result.transactions[0].category == "groceries"  # WHOLE FOODS
        assert result.transactions[0].confidence == 1.0
        assert result.transactions[1].category == "entertainment"  # NETFLIX
        assert result.transactions[2].category == "income"  # PAYROLL
        assert result.transactions[3].category == "uncategorized"  # MYSTERIOUS VENDOR

    def test_no_ai_leaves_unmatched(self, sample_transactions):
        cfg = Config()
        result = categorize_transactions(sample_transactions, cfg, use_ai=False)
        assert result.transactions[3].category == "uncategorized"
        assert result.transactions[3].confidence == 0.0

    def test_interactive_accept_suggestion(self, sample_transactions):
        cfg = Config()

        def mock_prompt(txn, suggestion, categories):
            return ("dining", txn.raw_description.lower())

        result = categorize_transactions(
            sample_transactions, cfg, use_ai=False, interactive=True, prompt_fn=mock_prompt,
        )
        # MYSTERIOUS VENDOR should now be "dining" via interactive prompt
        assert result.transactions[3].category == "dining"
        assert result.transactions[3].confidence == 1.0
        assert "dining" in result.learned_keywords
        assert "mysterious vendor xyz" in result.learned_keywords["dining"]

    def test_interactive_skip(self, sample_transactions):
        cfg = Config()

        def mock_prompt(txn, suggestion, categories):
            return None  # skip

        result = categorize_transactions(
            sample_transactions, cfg, use_ai=False, interactive=True, prompt_fn=mock_prompt,
        )
        assert result.transactions[3].category == "uncategorized"
        assert not result.learned_keywords

    def test_interactive_learns_for_remaining(self):
        """Learned keywords should apply to subsequent transactions in the same run."""
        from datetime import date
        from decimal import Decimal

        txns = [
            Transaction(transaction_date=date(2024, 1, 1), raw_description="UNIQUE STORE ABC", amount=Decimal("-10")),
            Transaction(transaction_date=date(2024, 1, 2), raw_description="UNIQUE STORE ABC", amount=Decimal("-20")),
        ]
        cfg = Config()
        call_count = 0

        def mock_prompt(txn, suggestion, categories):
            nonlocal call_count
            call_count += 1
            return ("shopping", txn.raw_description.lower())

        result = categorize_transactions(txns, cfg, use_ai=False, interactive=True, prompt_fn=mock_prompt)
        # First txn prompts, second should auto-match from learned keyword
        assert call_count == 1
        assert result.transactions[0].category == "shopping"
        assert result.transactions[1].category == "shopping"
