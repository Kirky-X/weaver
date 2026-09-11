# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for call_at user_content cache-key stability.

The LLM response cache key is derived from the request payload, which
includes `user_content` (a JSON serialization of the call payload). If
tracking fields (article_id/task_id) leak into user_content, two calls
with identical semantic content but different article_ids produce
different cache keys → permanent cache miss across reprocessing /
similar content.

These tests verify user_content excludes NON_SEMANTIC_FIELDS so the
cache key is stable, while tracing fields still flow through to
self.call() as kwargs.
"""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from core.llm.types import CallPoint, GlobalConfig, Label, LLMType, ProviderConfig


def _make_label(provider: str = "openai", model: str = "gpt-4o") -> Label:
    return Label(llm_type=LLMType.CHAT, provider=provider, model=model)


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
    return LLMClient(providers=providers, global_config=config, event_bus=event_bus)


def _wire_client(client: "LLMClient") -> None:
    """Wire router/smart_router/prompts so call_at reaches user_content build."""
    client._router.get_call_point_route = MagicMock(return_value=[_make_label()])
    client._router.get_call_point_config = MagicMock(return_value=None)
    client._smart_router = None
    prompts = MagicMock()
    prompts.get.return_value = "system prompt"
    client._prompts = prompts


class TestSystemPromptDateStability:
    """system_prompt 不得含秒级时间戳前缀；同日逐字节稳定（R-llm-cache-001）。

    秒级时间戳会同时打穿客户端缓存 key（对 request_payload 哈希）与服务端
    前缀缓存；日期粒度且尾置后，同日内 system_prompt 逐字节稳定。
    """

    @pytest.mark.asyncio
    async def test_same_day_calls_produce_identical_system_prompt(self):
        client = _make_client()
        _wire_client(client)

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "result"
            await client.call_at(CallPoint.ANALYZE, {"body": "同日内容一"})
            await client.call_at(CallPoint.ANALYZE, {"body": "同日内容一"})
            sp1 = mock_call.call_args_list[0].args[1]["system_prompt"]
            sp2 = mock_call.call_args_list[1].args[1]["system_prompt"]
            assert sp1 == sp2

    @pytest.mark.asyncio
    async def test_system_prompt_has_date_line_not_prefix_timestamp(self):
        client = _make_client()
        _wire_client(client)

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "result"
            await client.call_at(CallPoint.ANALYZE, {"body": "内容"})
            system_prompt = mock_call.call_args.args[1]["system_prompt"]
            assert system_prompt.startswith("system prompt")
            assert "当前时间:" not in system_prompt
            assert re.search(r"当前日期: \d{4}-\d{2}-\d{2}", system_prompt)

    @pytest.mark.asyncio
    async def test_date_line_precedes_json_tail_for_structured_calls(self):
        client = _make_client()
        _wire_client(client)

        class _Out(BaseModel):
            ok: bool = True

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "result"
            await client.call_at(CallPoint.ANALYZE, {"body": "内容"}, output_model=_Out)
            system_prompt = mock_call.call_args.args[1]["system_prompt"]
            assert system_prompt.index("当前日期:") < system_prompt.index("【输出格式·强制】")
            assert system_prompt.endswith("禁止 JSON 以外任何文字。")

    @pytest.mark.asyncio
    async def test_cross_day_calls_differ_in_date_line(self):
        client = _make_client()
        _wire_client(client)

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "result"
            with patch("core.llm.client.get_current_date", return_value="2026-09-11"):
                await client.call_at(CallPoint.ANALYZE, {"body": "内容"})
            with patch("core.llm.client.get_current_date", return_value="2026-09-12"):
                await client.call_at(CallPoint.ANALYZE, {"body": "内容"})
            sp1 = mock_call.call_args_list[0].args[1]["system_prompt"]
            sp2 = mock_call.call_args_list[1].args[1]["system_prompt"]
            assert sp1 != sp2
            assert "2026-09-11" in sp1
            assert "2026-09-12" in sp2


class TestCallAtCacheStability:
    """user_content must exclude tracking fields → stable cache key."""

    @pytest.mark.asyncio
    async def test_user_content_excludes_tracking_fields(self):
        """article_id/task_id must NOT appear in user_content; semantic body must."""
        client = _make_client()
        _wire_client(client)

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "result"
            await client.call_at(
                CallPoint.CLEANER,
                {
                    "body": "semantic test content",
                    "article_id": "abc-123",
                    "task_id": "task-456",
                },
                article_id="abc-123",
                task_id="task-456",
            )
            request_payload = mock_call.call_args.args[1]
            user_content = request_payload["user_content"]
            assert "abc-123" not in user_content
            assert "task-456" not in user_content
            assert "semantic test content" in user_content

    @pytest.mark.asyncio
    async def test_same_content_different_article_id_same_user_content(self):
        """Two calls with identical semantic content but different article_id
        must produce identical user_content (→ identical cache key)."""
        client = _make_client()
        _wire_client(client)

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "result"
            await client.call_at(
                CallPoint.CLEANER,
                {"body": "same content", "article_id": "id-1"},
                article_id="id-1",
            )
            await client.call_at(
                CallPoint.CLEANER,
                {"body": "same content", "article_id": "id-2"},
                article_id="id-2",
            )
            uc1 = mock_call.call_args_list[0].args[1]["user_content"]
            uc2 = mock_call.call_args_list[1].args[1]["user_content"]
            assert uc1 == uc2

    @pytest.mark.asyncio
    async def test_tracing_fields_still_forwarded_to_call(self):
        """article_id/task_id must still reach self.call() as kwargs for tracing."""
        client = _make_client()
        _wire_client(client)

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "result"
            await client.call_at(
                CallPoint.CLEANER,
                {"body": "content", "article_id": "abc-123"},
                article_id="abc-123",
                task_id="task-456",
            )
            assert mock_call.call_args.kwargs.get("article_id") == "abc-123"
            assert mock_call.call_args.kwargs.get("task_id") == "task-456"
