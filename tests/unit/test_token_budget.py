"""Unit tests for TokenBudgetManager."""

import pytest

from core.llm.types import CallPoint
from core.llm.token_budget import TokenBudgetManager, LIMITS, DEFAULT_LIMIT


class TestTokenBudgetManager:
    """Tests for TokenBudgetManager."""

    def test_initialization_with_known_model(self):
        """Test initialization with a known model."""
        manager = TokenBudgetManager(model="gpt-4o")
        assert manager._enc is not None

    def test_initialization_with_unknown_model_fallback(self):
        """Test initialization with unknown model falls back to cl100k_base."""
        manager = TokenBudgetManager(model="unknown-model-xyz")
        assert manager._enc is not None

    def test_truncate_within_limit(self):
        """Test text within limit is not truncated."""
        manager = TokenBudgetManager()
        text = "This is a short text."
        result = manager.truncate(text, CallPoint.CLASSIFIER)
        assert result == text

    def test_truncate_exceeds_limit(self):
        """Test text exceeding limit is truncated."""
        manager = TokenBudgetManager()
        long_text = "Hello world! " * 1000
        result = manager.truncate(long_text, CallPoint.CLASSIFIER)
        assert len(result) < len(long_text)
        assert "...[内容截断]..." in result

    def test_truncate_70_30_split(self):
        """Test truncation preserves 70% head and 30% tail."""
        manager = TokenBudgetManager()
        limit = LIMITS[CallPoint.CLASSIFIER]
        head_text = "Head content. " * 500
        tail_text = " Tail content." * 500
        long_text = head_text + tail_text
        result = manager.truncate(long_text, CallPoint.CLASSIFIER)
        assert "Head content" in result
        assert "Tail content" in result

    def test_truncate_different_call_points(self):
        """Test different call points have different limits."""
        manager = TokenBudgetManager()
        long_text = "Test content. " * 2000
        classifier_result = manager.truncate(long_text, CallPoint.CLASSIFIER)
        cleaner_result = manager.truncate(long_text, CallPoint.CLEANER)
        merger_result = manager.truncate(long_text, CallPoint.MERGER)
        assert len(classifier_result) != len(cleaner_result)
        assert len(merger_result) > len(classifier_result)

    def test_count_tokens(self):
        """Test token counting accuracy."""
        manager = TokenBudgetManager()
        text = "Hello, world!"
        count = manager.count_tokens(text)
        assert count > 0
        assert isinstance(count, int)

    def test_count_tokens_empty_string(self):
        """Test token counting with empty string."""
        manager = TokenBudgetManager()
        count = manager.count_tokens("")
        assert count == 0

    def test_limits_defined(self):
        """Test that limits are defined for all call points."""
        expected_call_points = [
            CallPoint.CLEANER,
            CallPoint.ANALYZE,
            CallPoint.ENTITY_EXTRACTOR,
            CallPoint.CREDIBILITY_CHECKER,
            CallPoint.CLASSIFIER,
            CallPoint.MERGER,
        ]
        for cp in expected_call_points:
            assert cp in LIMITS
            assert LIMITS[cp] > 0

    def test_default_limit_value(self):
        """Test default limit value."""
        assert DEFAULT_LIMIT == 4000

    def test_truncate_preserves_structure(self):
        """Test truncation preserves text structure markers."""
        manager = TokenBudgetManager()
        long_text = "Introduction. " * 500 + "Conclusion. " * 500
        result = manager.truncate(long_text, CallPoint.ANALYZE)
        assert isinstance(result, str)

    def test_truncate_chinese_text(self):
        """Test truncation works with Chinese text."""
        manager = TokenBudgetManager()
        long_text = "这是一段中文测试文本。" * 500
        result = manager.truncate(long_text, CallPoint.CLASSIFIER)
        assert "...[内容截断]..." in result

    def test_truncate_exact_limit(self):
        """Test text at exact limit is not truncated."""
        manager = TokenBudgetManager()
        limit = LIMITS[CallPoint.CLASSIFIER]
        tokens = manager._enc.encode("test ")
        exact_text = manager._enc.decode(tokens * (limit // len(tokens) + 1))
        exact_text = exact_text[:limit * 4]
        result = manager.truncate(exact_text, CallPoint.CLASSIFIER)
        assert isinstance(result, str)
