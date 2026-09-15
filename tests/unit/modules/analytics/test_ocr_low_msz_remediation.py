# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""T009 LOW remediation behaviour tests: modules/analytics batch (#msz)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.event import LLMCompareEvent
from modules.analytics.llm_compare.aggregator import aggregate_compare_data
from modules.analytics.llm_compare.buffer import EvalCompareBuffer
from modules.analytics.sentiment_analyzer import (
    SentimentAnalyzer,
    SentimentAnalyzerConfig,
)


class TestLatencyRoundingNotTruncation:
    """#209: latency sums must round instead of truncating toward zero."""

    @pytest.mark.asyncio
    async def test_fractional_latency_rounds(self):
        cache = MagicMock()
        cache.hgetall = AsyncMock(return_value={})
        pipe = MagicMock()
        pipe.__aenter__ = AsyncMock(return_value=pipe)
        pipe.__aexit__ = AsyncMock(return_value=False)
        cache.pipeline.return_value = pipe

        buffer = EvalCompareBuffer(cache=cache)
        event = LLMCompareEvent(
            call_point="eval",
            primary_model="a",
            candidate_model="b",
            primary_latency=1234.9,
            candidate_latency=10.4,
            primary_success=True,
            candidate_success=False,
            timestamp=datetime(2026, 9, 16, 10, 0, tzinfo=UTC),
        )

        await buffer.accumulate(event)

        hincrby_values = [c.args[2] for c in pipe.hincrby.call_args_list]
        assert 1235 in hincrby_values, f"expected rounded 1235, got {hincrby_values}"
        assert 10 in hincrby_values, f"expected rounded 10, got {hincrby_values}"

    @pytest.mark.asyncio
    async def test_field_names_come_from_helper(self):
        """#162: accumulate builds fields via _make_field_name (single source)."""
        cache = MagicMock()
        cache.hgetall = AsyncMock(return_value={})
        pipe = MagicMock()
        pipe.__aenter__ = AsyncMock(return_value=pipe)
        pipe.__aexit__ = AsyncMock(return_value=False)
        cache.pipeline.return_value = pipe

        buffer = EvalCompareBuffer(cache=cache)
        event = LLMCompareEvent(
            call_point="cp",
            primary_model="p",
            candidate_model="c",
            primary_latency=1.0,
            candidate_latency=1.0,
            primary_success=True,
            candidate_success=True,
            timestamp=datetime(2026, 9, 16, 10, 0, tzinfo=UTC),
        )

        await buffer.accumulate(event)

        fields = [c.args[1] for c in pipe.hincrby.call_args_list]
        assert "cp::p::c::count" in fields
        assert "cp::p::c::primary_latency_sum" in fields


class TestAggregateCompareDataReturnsPlainDict:
    """#160: callers must not silently materialize defaultdict records."""

    def test_returns_plain_dict(self):
        data = {
            "cp::a::b::count": "3",
            "cp::a::b::primary_success": "2",
        }
        result = aggregate_compare_data(data)
        assert type(result) is dict
        # Aggregator template-initializes all 5 metrics per key; metrics
        # absent from the input hash stay at 0.
        assert result == {
            ("cp", "a", "b"): {
                "count": 3,
                "primary_latency_sum": 0,
                "candidate_latency_sum": 0,
                "primary_success": 2,
                "candidate_success": 0,
            }
        }

    def test_unknown_key_access_raises_key_error(self):
        result = aggregate_compare_data({})
        with pytest.raises(KeyError):
            result[("missing", "key", "here")]


class TestSkepScoreTypeGuard:
    """#222: a non-numeric SKEP score degrades to fallback, not TypeError."""

    @pytest.mark.asyncio
    async def test_none_score_degrades_without_raising(self):
        analyzer = SentimentAnalyzer(
            config=SentimentAnalyzerConfig(enabled=False),
            llm_client=None,
        )
        # run_in_executor invokes self._skep synchronously in a thread.
        analyzer._skep = MagicMock(return_value=[{"label": "positive", "score": None}])

        # The guard must turn the invalid score into a degraded result
        # instead of raising TypeError on the threshold comparison.
        result = await SentimentAnalyzer._analyze_with_skep(analyzer, "text")

        assert result["source"] == "skep_fallback"
        assert result["sentiment_score"] == 0.0


class TestLLMMaxInputLengthConfig:
    """#166: LLM fallback truncation is configurable, not hardcoded."""

    def test_default_is_2000(self):
        config = SentimentAnalyzerConfig()
        assert config.llm_max_input_length == 2000

    @pytest.mark.asyncio
    async def test_custom_limit_truncates_payload(self):
        llm = MagicMock()
        llm.call_at = AsyncMock(return_value={"sentiment": "positive", "sentiment_score": 0.9})
        analyzer = SentimentAnalyzer(
            config=SentimentAnalyzerConfig(enabled=False, llm_max_input_length=8),
            llm_client=llm,
        )

        await analyzer._analyze_with_llm("abcdefghijklmnopqrstuvwxyz")

        payload = llm.call_at.call_args[0][1]
        assert payload == {"text": "abcdefgh"}
