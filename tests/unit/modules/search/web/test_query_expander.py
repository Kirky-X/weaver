# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for modules.search.web.query_expander module.

Covers R-web-search-008: LLM-driven query expansion. A broad query like
"菲律宾" gets expanded into focused variants ("菲律宾 仁爱礁",
"菲律宾 南海") so Bing surfaces topical news rather than encyclopedic
overviews.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.types import CallPoint
from modules.search.web.query_expander import LLMQueryExpander


class TestLLMQueryExpanderInit:
    """Test LLMQueryExpander initialization."""

    def test_init_with_llm_client(self):
        """Test initialization with LLM client."""
        mock_llm = MagicMock()
        expander = LLMQueryExpander(mock_llm)
        assert expander._llm is mock_llm


class TestLLMQueryExpanderExpand:
    """Test expand method with various LLM responses."""

    @pytest.fixture
    def expander(self):
        """Create LLMQueryExpander with mock LLM."""
        mock_llm = AsyncMock()
        return LLMQueryExpander(mock_llm)

    @pytest.mark.asyncio
    async def test_expand_returns_list_of_strings(self, expander):
        """Test successful expansion returns list of strings."""
        expander._llm.call = AsyncMock(
            return_value='["菲律宾 仁爱礁", "菲律宾 南海", "菲律宾 总统"]'
        )

        result = await expander.expand("菲律宾")

        assert isinstance(result, list)
        assert all(isinstance(q, str) for q in result)
        assert "菲律宾 仁爱礁" in result

    @pytest.mark.asyncio
    async def test_expand_does_not_include_original_query(self, expander):
        """Test that the original query is NOT included in expansion."""
        expander._llm.call = AsyncMock(return_value='["菲律宾 仁爱礁", "菲律宾 南海"]')

        result = await expander.expand("菲律宾")

        assert "菲律宾" not in result

    @pytest.mark.asyncio
    async def test_expand_respects_max_terms(self, expander):
        """Test that result is truncated to max_terms."""
        expander._llm.call = AsyncMock(
            return_value='["菲律宾 仁爱礁", "菲律宾 南海", "菲律宾 总统", "菲律宾 经济"]'
        )

        result = await expander.expand("菲律宾", max_terms=2)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_expand_max_terms_zero_returns_empty(self, expander):
        """Test max_terms=0 returns empty list."""
        expander._llm.call = AsyncMock(return_value='["a", "b"]')

        result = await expander.expand("菲律宾", max_terms=0)

        assert result == []

    @pytest.mark.asyncio
    async def test_expand_max_terms_negative_returns_empty(self, expander):
        """Test max_terms<0 returns empty list."""
        expander._llm.call = AsyncMock(return_value='["a", "b"]')

        result = await expander.expand("菲律宾", max_terms=-1)

        assert result == []

    @pytest.mark.asyncio
    async def test_expand_empty_query_returns_empty(self, expander):
        """Test empty query returns empty list without calling LLM."""
        expander._llm.call = AsyncMock(return_value='["should_not_be_called"]')

        result = await expander.expand("")

        assert result == []
        expander._llm.call.assert_not_called()

    @pytest.mark.asyncio
    async def test_expand_whitespace_query_returns_empty(self, expander):
        """Test whitespace-only query returns empty list."""
        expander._llm.call = AsyncMock(return_value='["should_not_be_called"]')

        result = await expander.expand("   ")

        assert result == []

    @pytest.mark.asyncio
    async def test_expand_llm_returns_non_json_returns_empty(self, expander):
        """Test LLM returning non-JSON falls back to empty list."""
        expander._llm.call = AsyncMock(return_value="Sorry, I cannot help with that.")

        result = await expander.expand("菲律宾")

        assert result == []

    @pytest.mark.asyncio
    async def test_expand_llm_returns_empty_string_returns_empty(self, expander):
        """Test LLM returning empty string falls back to empty list."""
        expander._llm.call = AsyncMock(return_value="")

        result = await expander.expand("菲律宾")

        assert result == []

    @pytest.mark.asyncio
    async def test_expand_llm_returns_empty_array(self, expander):
        """Test LLM returning [] is propagated."""
        expander._llm.call = AsyncMock(return_value="[]")

        result = await expander.expand("菲律宾")

        assert result == []

    @pytest.mark.asyncio
    async def test_expand_llm_raises_returns_empty(self, expander):
        """Test LLM raising exception falls back to empty list."""
        expander._llm.call = AsyncMock(side_effect=Exception("LLM timeout"))

        result = await expander.expand("菲律宾")

        assert result == []

    @pytest.mark.asyncio
    async def test_expand_llm_returns_non_array_json_returns_empty(self, expander):
        """Test LLM returning JSON object (not array) falls back to empty list."""
        expander._llm.call = AsyncMock(return_value='{"queries": ["a", "b"]}')

        result = await expander.expand("菲律宾")

        assert result == []

    @pytest.mark.asyncio
    async def test_expand_filters_non_string_elements(self, expander):
        """Test non-string elements in the returned array are filtered out."""
        expander._llm.call = AsyncMock(
            return_value='["菲律宾 仁爱礁", 123, null, "菲律宾 南海", true]'
        )

        result = await expander.expand("菲律宾")

        assert result == ["菲律宾 仁爱礁", "菲律宾 南海"]

    @pytest.mark.asyncio
    async def test_expand_strips_whitespace_from_each_term(self, expander):
        """Test each expanded term has surrounding whitespace stripped."""
        expander._llm.call = AsyncMock(return_value='["  菲律宾 仁爱礁  ", " 菲律宾 南海"]')

        result = await expander.expand("菲律宾")

        assert result == ["菲律宾 仁爱礁", "菲律宾 南海"]

    @pytest.mark.asyncio
    async def test_expand_deduplicates_terms(self, expander):
        """Test duplicate terms are deduplicated (case-sensitive)."""
        expander._llm.call = AsyncMock(
            return_value='["菲律宾 仁爱礁", "菲律宾 仁爱礁", "菲律宾 南海"]'
        )

        result = await expander.expand("菲律宾")

        assert result == ["菲律宾 仁爱礁", "菲律宾 南海"]

    @pytest.mark.asyncio
    async def test_expand_filters_out_empty_strings(self, expander):
        """Test empty strings within the array are filtered out."""
        expander._llm.call = AsyncMock(return_value='["菲律宾 仁爱礁", "", "  ", "菲律宾 南海"]')

        result = await expander.expand("菲律宾")

        assert result == ["菲律宾 仁爱礁", "菲律宾 南海"]

    @pytest.mark.asyncio
    async def test_expand_uses_query_expander_call_point(self, expander):
        """Test that expand uses CallPoint.QUERY_EXPANDER."""
        expander._llm.call = AsyncMock(return_value='["菲律宾 仁爱礁"]')

        await expander.expand("菲律宾")

        call_kwargs = expander._llm.call.call_args.kwargs
        assert call_kwargs["call_point"] == CallPoint.QUERY_EXPANDER

    @pytest.mark.asyncio
    async def test_expand_uses_agnes_flash_label(self, expander):
        """Test that expand uses the agnes-2.0-flash model label."""
        expander._llm.call = AsyncMock(return_value='["菲律宾 仁爱礁"]')

        await expander.expand("菲律宾")

        call_kwargs = expander._llm.call.call_args.kwargs
        assert call_kwargs["label"] == "chat.agnes.agnes-2.0-flash"

    @pytest.mark.asyncio
    async def test_expand_passes_query_in_payload(self, expander):
        """Test that the original query is embedded in the LLM payload."""
        expander._llm.call = AsyncMock(return_value='["菲律宾 仁爱礁"]')

        await expander.expand("菲律宾")

        call_kwargs = expander._llm.call.call_args.kwargs
        payload = call_kwargs["payload"]
        assert "user_content" in payload
        assert "菲律宾" in payload["user_content"]

    @pytest.mark.asyncio
    async def test_expand_payload_contains_max_terms_hint(self, expander):
        """Test payload includes max_terms hint so LLM knows the limit."""
        expander._llm.call = AsyncMock(return_value='["菲律宾 仁爱礁"]')

        await expander.expand("菲律宾", max_terms=5)

        call_kwargs = expander._llm.call.call_args.kwargs
        payload = call_kwargs["payload"]
        assert "5" in payload["user_content"]

    @pytest.mark.asyncio
    async def test_expand_truncates_after_dedup_and_filter(self, expander):
        """Test max_terms applies AFTER dedup + filter, not before."""
        # LLM returns 4 items with 1 duplicate and 1 non-string
        # → after dedup+filter: ["菲律宾 仁爱礁", "菲律宾 南海", "菲律宾 总统"]
        # → max_terms=2 → final = ["菲律宾 仁爱礁", "菲律宾 南海"]
        expander._llm.call = AsyncMock(
            return_value='["菲律宾 仁爱礁", "菲律宾 南海", 123, "菲律宾 仁爱礁", "菲律宾 总统"]'
        )

        result = await expander.expand("菲律宾", max_terms=2)

        assert result == ["菲律宾 仁爱礁", "菲律宾 南海"]

    @pytest.mark.asyncio
    async def test_expand_preserves_order_from_llm(self, expander):
        """Test that the original LLM output order is preserved."""
        expander._llm.call = AsyncMock(
            return_value='["菲律宾 南海", "菲律宾 仁爱礁", "菲律宾 总统"]'
        )

        result = await expander.expand("菲律宾")

        assert result == ["菲律宾 南海", "菲律宾 仁爱礁", "菲律宾 总统"]


class TestLLMQueryExpanderProtocolConformance:
    """Test that LLMQueryExpander conforms to QueryExpanderProtocol."""

    def test_satisfies_protocol(self):
        """Test that LLMQueryExpander instance satisfies QueryExpanderProtocol."""
        from modules.search.web.protocol import QueryExpanderProtocol

        expander = LLMQueryExpander(MagicMock())
        assert isinstance(expander, QueryExpanderProtocol)
