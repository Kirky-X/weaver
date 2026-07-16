# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for LLMClient.call_at article_id/task_id tracing."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.llm.types import CallPoint, GlobalConfig, Label, LLMType, ProviderConfig


def _make_label(provider: str = "openai", model: str = "gpt-4o") -> Label:
    return Label(
        llm_type=LLMType.CHAT,
        provider=provider,
        model=model,
    )


def _make_client() -> "LLMClient":
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
    config = GlobalConfig(providers=providers)
    event_bus = EventBus()
    return LLMClient(
        providers=providers,
        global_config=config,
        event_bus=event_bus,
    )


class TestCallAtTracing:
    """Tests for call_at passing article_id and task_id to call()."""

    @pytest.mark.asyncio
    async def test_call_at_passes_article_id_to_call(self):
        """call_at should forward article_id to self.call()."""
        client = _make_client()

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "result"
            # Mock the router to avoid "Call point not configured" error
            client._router.get_call_point_route = MagicMock(return_value=[_make_label()])
            client._router.get_call_point_config = MagicMock(return_value=None)
            client._smart_router = None
            client._prompts = None

            await client.call_at(
                CallPoint.CLEANER,
                {"body": "test"},
                article_id="abc-123",
                task_id="task-456",
            )

            mock_call.assert_called_once()
            assert mock_call.call_args.kwargs.get("article_id") == "abc-123"

    @pytest.mark.asyncio
    async def test_call_at_passes_task_id_to_call(self):
        """call_at should forward task_id to self.call()."""
        client = _make_client()

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "result"
            client._router.get_call_point_route = MagicMock(return_value=[_make_label()])
            client._router.get_call_point_config = MagicMock(return_value=None)
            client._smart_router = None
            client._prompts = None

            await client.call_at(
                CallPoint.CLEANER,
                {"body": "test"},
                article_id="abc-123",
                task_id="task-456",
            )

            mock_call.assert_called_once()
            assert mock_call.call_args.kwargs.get("task_id") == "task-456"

    @pytest.mark.asyncio
    async def test_call_at_defaults_article_id_none(self):
        """call_at without article_id should pass None."""
        client = _make_client()

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "result"
            client._router.get_call_point_route = MagicMock(return_value=[_make_label()])
            client._router.get_call_point_config = MagicMock(return_value=None)
            client._smart_router = None
            client._prompts = None

            await client.call_at(CallPoint.CLEANER, {"body": "test"})

            mock_call.assert_called_once()
            assert mock_call.call_args.kwargs.get("article_id") is None

    @pytest.mark.asyncio
    async def test_call_at_defaults_task_id_none(self):
        """call_at without task_id should pass None."""
        client = _make_client()

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "result"
            client._router.get_call_point_route = MagicMock(return_value=[_make_label()])
            client._router.get_call_point_config = MagicMock(return_value=None)
            client._smart_router = None
            client._prompts = None

            await client.call_at(CallPoint.CLEANER, {"body": "test"})

            mock_call.assert_called_once()
            assert mock_call.call_args.kwargs.get("task_id") is None


class TestEmitUsageEventTracing:
    """Tests for _emit_usage_event passing article_id/task_id to LLMUsageEvent."""

    @pytest.mark.asyncio
    async def test_emit_usage_event_includes_article_id(self):
        """_emit_usage_event should include article_id in LLMUsageEvent."""
        client = _make_client()
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()
        client._event_bus = event_bus

        await client._emit_usage_event(
            label=_make_label(),
            call_point=CallPoint.CLEANER,
            latency_ms=100.0,
            token_usage=None,
            success=True,
            article_id="abc-123",
            task_id="task-456",
        )

        event_bus.publish.assert_called_once()
        event = event_bus.publish.call_args.args[0]
        assert event.article_id == "abc-123"
        assert event.task_id == "task-456"

    @pytest.mark.asyncio
    async def test_emit_usage_event_defaults_none(self):
        """_emit_usage_event without article_id/task_id should default to None."""
        client = _make_client()
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()
        client._event_bus = event_bus

        await client._emit_usage_event(
            label=_make_label(),
            call_point=CallPoint.CLEANER,
            latency_ms=100.0,
            token_usage=None,
            success=True,
        )

        event_bus.publish.assert_called_once()
        event = event_bus.publish.call_args.args[0]
        assert event.article_id is None
        assert event.task_id is None
