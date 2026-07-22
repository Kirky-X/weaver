# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for _JSON_FORMAT_TAIL appended to structured-output system prompts.

Validates that call_at appends the JSON format guard to the END of system_prompt
when output_model is present (structured output), and does NOT append it for
plain-text calls (output_model=None), and that retry_hint stays before the tail.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from core.llm.types import CallPoint, GlobalConfig, Label, LLMType, ProviderConfig


def _make_label() -> Label:
    return Label(llm_type=LLMType.CHAT, provider="openai", model="gpt-4o")


def _make_client():  # type: ignore[no-untyped-def]
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
    return LLMClient(
        providers=providers,
        global_config=GlobalConfig(providers=providers),
        event_bus=EventBus(),
    )


def _setup(client, base_prompt: str = "BASE_SYSTEM_PROMPT") -> None:
    """Wire client so call_at enters the prompt-assembly path, mock self.call()."""
    client._router.get_call_point_route = MagicMock(return_value=[_make_label()])
    client._router.get_call_point_config = MagicMock(return_value=None)
    client._smart_router = None
    # PromptLoader-like mock: .get(name) returns a non-empty system prompt
    client._prompts = MagicMock()
    client._prompts.get.return_value = base_prompt


def _captured_system_prompt(mock_call) -> str:
    """Extract system_prompt from the payload passed to self.call()."""
    # call_at calls self.call(labels[0], request_payload, ...) — payload is args[1]
    request_payload = mock_call.call_args.args[1]
    return request_payload["system_prompt"]


class _DummyOutput(BaseModel):
    """Trivial Pydantic model to simulate a structured output_model."""

    value: int = 0


class TestJsonFormatTail:
    """_JSON_FORMAT_TAIL appended only for structured output, at the very end."""

    @pytest.mark.asyncio
    async def test_tail_appended_when_output_model_present(self):
        from core.llm.client import _JSON_FORMAT_TAIL

        client = _make_client()
        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = _DummyOutput()
            _setup(client)

            await client.call_at(CallPoint.CLEANER, {"body": "t"}, output_model=_DummyOutput)

            system_prompt = _captured_system_prompt(mock_call)
            # Tail must be present and at the very end (recency bias)
            assert _JSON_FORMAT_TAIL in system_prompt
            assert system_prompt.endswith(_JSON_FORMAT_TAIL)

    @pytest.mark.asyncio
    async def test_no_tail_when_output_model_none(self):
        """Plain-text calls (no output_model) must NOT be polluted by the JSON guard."""
        from core.llm.client import _JSON_FORMAT_TAIL

        client = _make_client()
        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "plain-text-result"
            _setup(client)

            await client.call_at(CallPoint.CLEANER, {"body": "t"})  # no output_model

            system_prompt = _captured_system_prompt(mock_call)
            assert _JSON_FORMAT_TAIL not in system_prompt

    @pytest.mark.asyncio
    async def test_tail_after_retry_hint(self):
        """When retry_hint is present, the tail must still be the LAST segment."""
        from core.llm.client import _JSON_FORMAT_TAIL

        client = _make_client()
        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = _DummyOutput()
            _setup(client)

            await client.call_at(
                CallPoint.CLEANER,
                {"body": "t", "_retry_hint": "上一次输出解析失败，请返回完整 JSON"},
                output_model=_DummyOutput,
            )

            system_prompt = _captured_system_prompt(mock_call)
            assert system_prompt.endswith(_JSON_FORMAT_TAIL)
            # retry_hint must appear BEFORE the format tail
            assert system_prompt.index("上一次输出解析失败") < system_prompt.index(
                "【输出格式·强制】"
            )
