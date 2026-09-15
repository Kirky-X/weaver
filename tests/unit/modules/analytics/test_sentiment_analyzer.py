# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for PaddleNLP SKEP sentiment analyzer."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock paddlenlp module before importing
mock_paddlenlp = MagicMock()
sys.modules["paddlenlp"] = mock_paddlenlp

from modules.analytics.sentiment_analyzer import (
    SentimentAnalyzer,
    SentimentAnalyzerConfig,
)


@pytest.fixture
def config() -> SentimentAnalyzerConfig:
    """Default configuration for tests."""
    return SentimentAnalyzerConfig()


@pytest.fixture
def analyzer(config: SentimentAnalyzerConfig) -> SentimentAnalyzer:
    """SentimentAnalyzer instance with mocked SKEP."""
    with patch("paddlenlp.Taskflow") as mock_taskflow:
        mock_skep = MagicMock()
        mock_taskflow.return_value = mock_skep
        return SentimentAnalyzer(config=config)


@pytest.fixture
def analyzer_with_llm(config: SentimentAnalyzerConfig) -> SentimentAnalyzer:
    """SentimentAnalyzer instance with mocked SKEP and LLM."""
    with patch("paddlenlp.Taskflow") as mock_taskflow:
        mock_skep = MagicMock()
        mock_taskflow.return_value = mock_skep

        llm = AsyncMock()
        llm.call_at = AsyncMock(
            return_value={
                "sentiment": "neutral",
                "sentiment_score": 0.5,
            }
        )
        return SentimentAnalyzer(config=config, llm_client=llm)


class TestSentimentAnalyzerConfig:
    """Test SentimentAnalyzerConfig defaults."""

    def test_default_config(self, config: SentimentAnalyzerConfig) -> None:
        """Test that default config values are set correctly."""
        assert config.enabled is True
        assert config.model_name == "skep_ernie_1.0_large_chinese"
        assert config.max_input_length == 512
        assert config.confidence_threshold == 0.6
        assert config.fallback_to_llm is True


class TestSKEPAnalysis:
    """Test SKEP sentiment analysis."""

    @pytest.mark.asyncio
    async def test_high_confidence_skep_result(self, analyzer: SentimentAnalyzer) -> None:
        """Test that high confidence SKEP result is used directly."""
        # Mock SKEP to return high confidence result
        analyzer._skep = MagicMock(
            return_value=[{"text": "测试文本", "label": "positive", "score": 0.95}]
        )

        result = await analyzer.analyze("某公司季度营收同比增长38%")

        assert result["sentiment"] == "positive"
        assert result["source"] == "skep"
        assert result["confidence"] >= 0.6

    @pytest.mark.asyncio
    async def test_low_confidence_fallback_to_llm(
        self, analyzer_with_llm: SentimentAnalyzer
    ) -> None:
        """Test that low confidence SKEP result falls back to LLM."""
        # Mock SKEP to return low confidence result
        analyzer_with_llm._skep = MagicMock(
            return_value=[{"text": "测试文本", "label": "positive", "score": 0.4}]
        )

        result = await analyzer_with_llm.analyze("某公司季度营收同比增长38%")

        # Should fall back to LLM
        assert result["source"] == "llm"

    @pytest.mark.asyncio
    async def test_low_confidence_no_llm(self, analyzer: SentimentAnalyzer) -> None:
        """Test that low confidence SKEP result uses SKEP fallback when no LLM."""
        # Mock SKEP to return low confidence result
        analyzer._skep = MagicMock(
            return_value=[{"text": "测试文本", "label": "positive", "score": 0.4}]
        )

        result = await analyzer.analyze("某公司季度营收同比增长38%")

        # Should use SKEP fallback
        assert result["source"] == "skep_fallback"

    @pytest.mark.asyncio
    async def test_text_truncation(self, analyzer: SentimentAnalyzer) -> None:
        """Test that text is truncated to max_input_length."""
        # Create a long text
        long_text = "测试" * 1000  # 2000 characters

        # Mock SKEP
        analyzer._skep = MagicMock(
            return_value=[{"text": long_text[:512], "label": "neutral", "score": 0.8}]
        )

        result = await analyzer.analyze(long_text)

        # Verify SKEP was called with truncated text
        analyzer._skep.assert_called_once()
        called_text = analyzer._skep.call_args[0][0]
        assert len(called_text) <= 512


class TestScoreNormalization:
    """Test score normalization."""

    def test_normalize_score(self, analyzer: SentimentAnalyzer) -> None:
        """Test score normalization to [0, 1] range."""
        assert analyzer._normalize_score(0.5) == 0.5
        assert analyzer._normalize_score(0.0) == 0.0
        assert analyzer._normalize_score(1.0) == 1.0

    def test_normalize_score_clamping(self, analyzer: SentimentAnalyzer) -> None:
        """Test that scores outside [0, 1] are clamped."""
        assert analyzer._normalize_score(-0.1) == 0.0
        assert analyzer._normalize_score(1.1) == 1.0

    def test_normalize_score_skep_to_sentiment(self, analyzer: SentimentAnalyzer) -> None:
        """Test SKEP score to sentiment score conversion."""
        # SKEP confidence 0.95 -> sentiment_score 0.95
        assert analyzer._normalize_score(0.95) == 0.95

        # SKEP confidence 0.4 -> sentiment_score 0.4
        assert analyzer._normalize_score(0.4) == 0.4

    def test_normalize_score_string_input(self, analyzer: SentimentAnalyzer) -> None:
        """LLM string scores are coerced instead of raising TypeError (#221)."""
        assert analyzer._normalize_score("0.8") == 0.8
        assert analyzer._normalize_score("1.5") == 1.0
        assert analyzer._normalize_score("-2") == 0.0

    def test_normalize_score_none_and_garbage(self, analyzer: SentimentAnalyzer) -> None:
        """None / non-numeric scores degrade to 0.5 with a warning (#221)."""
        assert analyzer._normalize_score(None) == 0.5
        assert analyzer._normalize_score("high") == 0.5


class TestSentimentLabelMapping:
    """Test sentiment label mapping."""

    def test_positive_label(self, analyzer: SentimentAnalyzer) -> None:
        """Test positive label mapping."""
        assert analyzer._map_label("positive") == "positive"

    def test_negative_label(self, analyzer: SentimentAnalyzer) -> None:
        """Test negative label mapping."""
        assert analyzer._map_label("negative") == "negative"

    def test_neutral_label(self, analyzer: SentimentAnalyzer) -> None:
        """Test neutral label mapping."""
        assert analyzer._map_label("neutral") == "neutral"

    def test_unknown_label(self, analyzer: SentimentAnalyzer) -> None:
        """Test unknown label defaults to neutral."""
        assert analyzer._map_label("unknown") == "neutral"


class TestDegradedFields:
    """Test degraded fields tracking."""

    @pytest.mark.asyncio
    async def test_degraded_fields_on_llm_fallback(
        self, analyzer_with_llm: SentimentAnalyzer
    ) -> None:
        """Test that degraded_fields is set when falling back to LLM."""
        # Mock SKEP to return low confidence result
        analyzer_with_llm._skep = MagicMock(
            return_value=[{"text": "测试文本", "label": "positive", "score": 0.4}]
        )

        result = await analyzer_with_llm.analyze("某公司季度营收同比增长38%")

        # Should have degraded_fields
        assert "degraded_fields" in result
        assert "sentiment" in result["degraded_fields"]


class TestEdgeCases:
    """Test edge cases."""

    @pytest.mark.asyncio
    async def test_empty_text(self, analyzer: SentimentAnalyzer) -> None:
        """Test handling of empty text."""
        result = await analyzer.analyze("")

        # Should return default neutral sentiment
        assert result["sentiment"] == "neutral"
        assert result["source"] == "default"

    @pytest.mark.asyncio
    async def test_skep_exception(self, analyzer: SentimentAnalyzer) -> None:
        """Test handling of SKEP exception."""
        # Mock SKEP to raise exception
        analyzer._skep = MagicMock(side_effect=Exception("SKEP error"))

        result = await analyzer.analyze("测试文本")

        # Should return default neutral sentiment
        assert result["sentiment"] == "neutral"
        assert result["source"] == "error"

    @pytest.mark.asyncio
    async def test_skep_empty_result(self, analyzer: SentimentAnalyzer) -> None:
        """Test handling of SKEP empty result."""
        # Mock SKEP to return empty result
        analyzer._skep = MagicMock(return_value=[])

        result = await analyzer.analyze("测试文本")

        # Should return default neutral sentiment
        assert result["sentiment"] == "neutral"
        assert result["source"] == "default"


class TestExtractJsonFromText:
    """Quote-aware brace matching for LLM JSON extraction (#53)."""

    def test_braces_inside_strings_ignored(self, analyzer: SentimentAnalyzer) -> None:
        """A '}' inside a string value must not end the object (#53)."""
        text = (
            'thinking...\n{"sentiment": "positive", "note": "use {x} here", "sentiment_score": 0.9}'
        )
        result = analyzer._extract_json_from_text(text)

        assert result is not None
        assert result["sentiment"] == "positive"
        assert result["note"] == "use {x} here"
        assert result["sentiment_score"] == 0.9

    def test_recovers_after_trailing_unbalanced_brace(self, analyzer: SentimentAnalyzer) -> None:
        """A later unbalanced '{' falls back to the real object (#53)."""
        text = '{"sentiment": "positive", "sentiment_score": 0.7} trailing {oops'
        result = analyzer._extract_json_from_text(text)

        assert result == {"sentiment": "positive", "sentiment_score": 0.7}

    def test_object_amid_prose(self, analyzer: SentimentAnalyzer) -> None:
        """Flat JSON embedded in reasoning text is extracted (#53)."""
        text = 'I think {this is just thinking... {"sentiment": "negative", "sentiment_score": 0.2} done'
        result = analyzer._extract_json_from_text(text)

        assert result == {"sentiment": "negative", "sentiment_score": 0.2}

    def test_no_json_returns_none(self, analyzer: SentimentAnalyzer) -> None:
        """Prose without JSON yields None (#53)."""
        assert analyzer._extract_json_from_text("no braces here") is None
        assert analyzer._extract_json_from_text("{{{ unbalanced") is None

    def test_candidate_cap_bounds_pathological_input(self, analyzer: SentimentAnalyzer) -> None:
        """Brace-heavy prose terminates quickly via the candidate cap (#53)."""
        text = "{ " * 5000 + "no json at all"
        assert analyzer._extract_json_from_text(text) is None
