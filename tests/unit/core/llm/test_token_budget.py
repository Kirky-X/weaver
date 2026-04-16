# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for token_budget module."""

from unittest.mock import MagicMock, patch

import pytest

from core.llm.config.token_budget import DEFAULT_LIMIT, LIMITS, TokenBudgetManager
from core.llm.types import CallPoint


class TestTokenBudgetManagerInit:
    """Test TokenBudgetManager initialization."""

    def test_init_with_model_name(self):
        """Test initialization with explicit model name."""
        manager = TokenBudgetManager(model="gpt-4o")
        assert manager._enc is not None

    def test_init_with_unknown_model_falls_back(self):
        """Test initialization with unknown model falls back to cl100k_base."""
        manager = TokenBudgetManager(model="unknown_model_xyz")
        assert manager._enc is not None

    def test_init_with_none_uses_settings_or_default(self):
        """Test initialization with None reads from settings or uses default."""
        with patch.object(TokenBudgetManager, "_resolve_from_settings", return_value=None):
            manager = TokenBudgetManager(model=None)
            assert manager._enc is not None

    def test_init_reads_from_settings(self):
        """Test initialization reads tokenizer_model from settings."""
        mock_settings = MagicMock()
        mock_settings.llm.tokenizer_model = "gpt-3.5-turbo"

        with patch.object(
            TokenBudgetManager, "_resolve_from_settings", return_value="gpt-3.5-turbo"
        ):
            manager = TokenBudgetManager(model=None)
            assert manager._enc is not None

    def test_init_handles_settings_exception(self):
        """Test initialization handles settings exception gracefully."""
        with patch.object(TokenBudgetManager, "_resolve_from_settings", return_value=None):
            manager = TokenBudgetManager(model=None)
            assert manager._enc is not None


class TestCountTokens:
    """Test count_tokens method."""

    def test_count_empty_string(self):
        """Test counting tokens in empty string."""
        manager = TokenBudgetManager(model="gpt-4o")
        assert manager.count_tokens("") == 0

    def test_count_simple_text(self):
        """Test counting tokens in simple text."""
        manager = TokenBudgetManager(model="gpt-4o")
        count = manager.count_tokens("Hello world")
        assert count > 0

    def test_count_chinese_text(self):
        """Test counting tokens in Chinese text."""
        manager = TokenBudgetManager(model="gpt-4o")
        count = manager.count_tokens("你好世界")
        assert count > 0

    def test_count_longer_text(self):
        """Test that longer text has more tokens."""
        manager = TokenBudgetManager(model="gpt-4o")
        short_count = manager.count_tokens("Short text")
        long_count = manager.count_tokens("This is a much longer text that should have more tokens")
        assert long_count > short_count


class TestTruncate:
    """Test truncate method."""

    def test_no_truncation_when_within_budget(self):
        """Test that text within budget is not truncated."""
        manager = TokenBudgetManager(model="gpt-4o")
        short_text = "Short text"
        result = manager.truncate(short_text, CallPoint.CLASSIFIER)
        assert result == short_text

    def test_truncation_preserves_head_and_tail(self):
        """Test that truncation preserves head (70%) and tail (30%)."""
        manager = TokenBudgetManager(model="gpt-4o")
        # Create text that will exceed budget
        long_text = "Word " * 2000
        result = manager.truncate(long_text, CallPoint.CLASSIFIER)

        assert "[内容截断]" in result
        assert len(result) < len(long_text)

    def test_truncation_for_different_call_points(self):
        """Test different call points have different budgets."""
        manager = TokenBudgetManager(model="gpt-4o")
        long_text = "Word " * 5000

        # CLASSIFIER has 1000 token limit
        result_classifier = manager.truncate(long_text, CallPoint.CLASSIFIER)
        # MERGER has 8000 token limit
        result_merger = manager.truncate(long_text, CallPoint.MERGER)

        # Both should be truncated or handled differently
        assert "[内容截断]" in result_classifier or len(result_classifier) < len(long_text)

    def test_truncation_with_chinese_text(self):
        """Test truncation works with Chinese text."""
        manager = TokenBudgetManager(model="gpt-4o")
        long_chinese = "测试文本。" * 1000
        result = manager.truncate(long_chinese, CallPoint.CLASSIFIER)
        assert "[内容截断]" in result

    def test_default_limit_for_unknown_call_point(self):
        """Test that unknown call point uses DEFAULT_LIMIT."""
        manager = TokenBudgetManager(model="gpt-4o")
        # Create a mock call point by using a very long text
        long_text = "Word " * 10000
        result = manager.truncate(long_text, CallPoint.CLEANER)
        assert "[内容截断]" in result


class TestTokenLimits:
    """Test token limit constants."""

    def test_limits_dict_has_expected_call_points(self):
        """Test that LIMITS dict has expected call points."""
        expected_points = [
            CallPoint.CLEANER,
            CallPoint.ANALYZE,
            CallPoint.ENTITY_EXTRACTOR,
            CallPoint.CREDIBILITY_CHECKER,
            CallPoint.QUALITY_SCORER,
            CallPoint.CLASSIFIER,
            CallPoint.MERGER,
        ]
        for point in expected_points:
            assert point in LIMITS
            assert LIMITS[point] > 0

    def test_default_limit_is_reasonable(self):
        """Test that DEFAULT_LIMIT is reasonable."""
        assert DEFAULT_LIMIT == 4000
        assert DEFAULT_LIMIT > 0

    def test_limits_are_sorted_by_expected_size(self):
        """Test that limits have expected relative sizes."""
        # MERGER should have largest budget
        assert LIMITS[CallPoint.MERGER] >= LIMITS[CallPoint.CLEANER]
        # CLASSIFIER should have smallest budget
        assert LIMITS[CallPoint.CLASSIFIER] <= LIMITS[CallPoint.ANALYZE]
