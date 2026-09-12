# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for LLMClient.embed completeness guarantee.

Previously a missing/empty provider embedding was silently substituted
with a hardcoded 1024-dim zero vector; zero vectors pass truthiness
checks downstream, get persisted, and poison similarity search (all
texts become equally distant). The contract is now fail-loud.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from core.llm.types import GlobalConfig, Label, LLMType, ProviderConfig


def _make_client() -> Any:
    from core.event import EventBus
    from core.llm.client import LLMClient

    providers = [
        ProviderConfig(
            name="openai",
            type="openai",
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            rpm_limit=100,
            concurrency=5,
        )
    ]
    client = LLMClient(
        providers=providers,
        global_config=GlobalConfig(providers=providers),
        event_bus=EventBus(),
    )
    client._router.get_call_point_route = lambda cp: [
        Label(llm_type=LLMType.EMBEDDING, provider="openai", model="embed-1")
    ]
    client._router.get_call_point_config = lambda cp: None
    client._prompts = None
    return client


def _embedding_label() -> Label:
    return Label(llm_type=LLMType.EMBEDDING, provider="openai", model="embed-1")


class TestEmbedCompleteness:
    """embed() must never return zero-vector placeholders."""

    @pytest.mark.asyncio
    async def test_returns_full_result_when_provider_complete(self):
        client = _make_client()
        vectors = [[0.1] * 8, [0.2] * 8, [0.3] * 8]

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = vectors
            result = await client.embed(_embedding_label(), ["a", "b", "c"])

        assert result == vectors

    @pytest.mark.asyncio
    async def test_raises_when_provider_returns_fewer_vectors(self):
        """A short provider response must raise, not pad with zero vectors."""
        client = _make_client()

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = [[0.1] * 8]  # asked for 3, got 1
            with pytest.raises(ValueError, match="embedding_result_incomplete"):
                await client.embed(_embedding_label(), ["a", "b", "c"])

    @pytest.mark.asyncio
    async def test_raises_when_provider_returns_empty_vector(self):
        """An empty (falsy) vector in the response must raise."""
        client = _make_client()

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = [[0.1] * 8, []]
            with pytest.raises(ValueError, match="embedding_result_incomplete"):
                await client.embed(_embedding_label(), ["a", "b"])

    @pytest.mark.asyncio
    async def test_no_zero_vector_placeholder_in_output(self):
        """The hardcoded [0.0]*1024 placeholder must be gone for good."""
        import inspect

        from core.llm.client import LLMClient

        source = inspect.getsource(LLMClient.embed)
        assert "[0.0] * 1024" not in source
