# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for LLMCaller.chat response_format handling and batch_call caching.

Covers:
- dict JSON Schema constraints are injected into the user content
  (provider-agnostic) instead of being silently dropped;
- string "json" keeps the OpenAI-compatible json_object mode and never
  leaks a ``max_tokens=None`` into the API kwargs;
- batch_call caches BaseModel results via model_dump_json (previously the
  json.dumps TypeError was swallowed at debug level, so model results were
  never cached).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from core.llm.caller import LiteLLMCaller as LLMCaller
from core.llm.types import Label, LLMType


def _make_label(provider: str = "openai", model: str = "gpt-4o") -> Label:
    return Label(llm_type=LLMType.CHAT, provider=provider, model=model)


def _make_completion_response(content: str = "ok") -> MagicMock:
    """Build a litellm-shaped response mock for caller.chat."""
    response = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = "stop"
    response.choices = [choice]
    response.usage = None
    return response


def _make_pool_config() -> Any:
    return None


class TestCallerChatResponseFormat:
    """caller.chat must honour dict JSON Schema constraints."""

    @pytest.mark.asyncio
    async def test_dict_schema_injected_into_user_content(self):
        """A dict response_format lands in the user message, not the API kwargs."""
        caller = LLMCaller()
        schema = {
            "type": "object",
            "properties": {"amount": {"type": "number"}},
            "required": ["amount"],
        }

        with patch("core.llm.caller.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_completion_response('{"amount": 1}')
            await caller.chat(
                label=_make_label(),
                provider_type="openai",
                api_key="k",
                api_base="https://api.example.com",
                system_prompt="sys",
                user_content="extract funding",
                response_format=schema,
            )

        kwargs = mock_ac.call_args[1]
        # Raw schema dict must NOT be forwarded as response_format (Agnes
        # and other incompatible providers would break).
        assert "response_format" not in kwargs
        user_message = kwargs["messages"][1]["content"]
        assert "JSON Schema" in user_message
        assert json.dumps(schema, ensure_ascii=False) in user_message
        assert user_message.startswith("extract funding")

    @pytest.mark.asyncio
    async def test_json_string_uses_json_object_mode(self):
        """String "json" keeps the OpenAI-compatible json_object mode."""
        caller = LLMCaller()

        with patch("core.llm.caller.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_completion_response("{}")
            await caller.chat(
                label=_make_label(),
                provider_type="openai",
                api_key="k",
                api_base="https://api.example.com",
                system_prompt="sys",
                user_content="u",
                response_format="json",
            )

        kwargs = mock_ac.call_args[1]
        assert kwargs["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_json_mode_with_none_max_tokens_not_sent(self):
        """max_tokens=None must not reach the API kwargs (invalid payload)."""
        caller = LLMCaller()

        with patch("core.llm.caller.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_completion_response("{}")
            await caller.chat(
                label=_make_label(),
                provider_type="openai",
                api_key="k",
                api_base="https://api.example.com",
                system_prompt="sys",
                user_content="u",
                response_format="json",
                max_tokens=None,
            )

        kwargs = mock_ac.call_args[1]
        assert "max_tokens" not in kwargs

    @pytest.mark.asyncio
    async def test_no_response_format_untouched(self):
        """Without response_format the user content is passed unmodified."""
        caller = LLMCaller()

        with patch("core.llm.caller.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_completion_response("hi")
            await caller.chat(
                label=_make_label(),
                provider_type="openai",
                api_key="k",
                api_base="https://api.example.com",
                system_prompt="sys",
                user_content="plain prompt",
            )

        kwargs = mock_ac.call_args[1]
        assert "response_format" not in kwargs
        assert kwargs["messages"][1]["content"] == "plain prompt"


class TestBatchCallCacheSerialization:
    """batch_call must cache BaseModel results via model_dump_json."""

    class _Out(BaseModel):
        """Test output model."""

        amount: int
        company: str

    @pytest.mark.asyncio
    async def test_batch_call_caches_model_results(self):
        """Model results are serialized with model_dump_json, not json.dumps."""
        from core.llm.client import LLMClient
        from core.llm.types import GlobalConfig, ProviderConfig

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
            event_bus=MagicMock(),
        )
        client._router.get_call_point_route = lambda cp: [_make_label()]
        client._router.get_call_point_config = lambda cp: None
        client._smart_router = None
        client._prompts = None
        client._response_cache.clear()

        redis = MagicMock()
        redis.mset = AsyncMock()
        redis.expire = AsyncMock()
        client._redis = redis

        expected = self._Out(amount=42, company="Acme")
        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = expected
            results = await client.batch_call(
                label="chat::openai::gpt-4o",
                payloads=[{"user_content": "p1"}, {"user_content": "p2"}],
                call_point="classifier",
                output_model=self._Out,
            )

        assert results == [expected, expected]
        assert redis.mset.await_count == 1
        mapping = redis.mset.await_args[0][0]
        assert len(mapping) == 2
        for payload in mapping.values():
            data = json.loads(payload)
            # Round-trips back into the model — proves model_dump_json was used.
            assert self._Out.model_validate_json(data["content"]) == expected


def _patch_rerank_client(monkeypatch):
    """Replace core.llm.caller.AsyncOpenAI with a counting fake.

    Returns (created, closed): base_url lists recording construction and
    close() of each fake client.
    """
    created: list[str] = []
    closed: list[str] = []

    class FakeRerankClient:
        def __init__(
            self,
            api_key: str | None = None,
            base_url: str | None = None,
            timeout: float | None = None,
        ) -> None:
            created.append(base_url)
            self.close = AsyncMock(side_effect=lambda: closed.append(base_url))

    monkeypatch.setattr("core.llm.caller.AsyncOpenAI", FakeRerankClient)
    return created, closed


class TestRerankClientCacheCap:
    """The rerank client cache must stay bounded (FIFO eviction) and race-free."""

    @pytest.mark.asyncio
    async def test_cache_evicts_oldest_beyond_cap(self, monkeypatch):
        caller = LLMCaller()
        caller._RERANK_CLIENT_CAP = 2
        created, closed = _patch_rerank_client(monkeypatch)

        for i in range(4):
            await caller._get_rerank_client(f"https://api{i}.example.com", f"key-{i}", 10.0)

        assert len(caller._rerank_clients) == 2
        # The two oldest endpoints were evicted and their clients closed.
        assert ("https://api0.example.com", "key-0") not in caller._rerank_clients
        assert ("https://api1.example.com", "key-1") not in caller._rerank_clients
        assert ("https://api2.example.com", "key-2") in caller._rerank_clients
        assert ("https://api3.example.com", "key-3") in caller._rerank_clients
        assert created == [
            "https://api0.example.com",
            "https://api1.example.com",
            "https://api2.example.com",
            "https://api3.example.com",
        ]
        assert closed == ["https://api0.example.com", "https://api1.example.com"]

    @pytest.mark.asyncio
    async def test_same_endpoint_reuses_client(self, monkeypatch):
        caller = LLMCaller()
        created, _ = _patch_rerank_client(monkeypatch)
        a = await caller._get_rerank_client("https://api.example.com", "k", 10.0)
        b = await caller._get_rerank_client("https://api.example.com/", "k", 10.0)
        assert a is b
        assert len(caller._rerank_clients) == 1
        assert len(created) == 1

    @pytest.mark.asyncio
    async def test_concurrent_first_calls_create_single_client(self, monkeypatch):
        """Concurrent first calls for one endpoint must build exactly one client."""
        caller = LLMCaller()
        created, _ = _patch_rerank_client(monkeypatch)

        await asyncio.gather(
            *(caller._get_rerank_client("https://api.example.com", "k", 10.0) for _ in range(8))
        )

        assert len(created) == 1
        assert len(caller._rerank_clients) == 1
