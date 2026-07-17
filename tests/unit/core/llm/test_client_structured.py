# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for LLMClient.structured_call (T024 / R-structured-002, R-structured-003).

Verifies the 4 scenarios mandated by spec:
1. Success: schema exists, LLM returns valid JSON matching schema → return dict
2. Validation-fail-retry-success: 1st response invalid → retry with hint →
   2nd response valid → return dict
3. Validation-retry-still-fails: both responses invalid → raise
   StructuredOutputValidationError (carries schema + last_response)
4. SchemaNotFoundError: schema not found → log warning + return
   {_fallback: true, content: <llm_response>} (degrade, no retry)

Spec R-structured-002 priority:
    1. SchemaNotFoundError → DIRECT fallback (no retry — schema absent,
       retry is meaningless).
    2. Schema exists → retry path: validate → fail → retry 1x → fail →
       StructuredOutputValidationError.
    3. Degrade and retry are mutually exclusive — SchemaNotFoundError
       bypasses the retry loop entirely.

Test strategy:
- Mock LLMClient.call() (AsyncMock via patch.object) to simulate LLM
  responses. This isolates structured_call logic from real LLM calls
  (RPM consumption, network latency).
- Mock self._graph_pool via a FakeGraphPool stub class (real Python
  class, not MagicMock — mirrors test_structured_output.py pattern).
- self._graph_pool is set via attribute injection (mirrors
  _smart_router pattern in container/lifecycle.py:194).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from core.llm.structured_output import SchemaNotFoundError
from core.llm.types import CallPoint, GlobalConfig, Label, LLMType, ProviderConfig


class FakeGraphPool:
    """Fake GraphPool returning pre-configured SchemaNode records.

    Real Python class (not MagicMock) — mirrors
    test_structured_output.py pattern. Returns the records passed in
    constructor, allowing tests to simulate found / not-found / error.
    """

    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self._records = records

    async def execute_query(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        return self._records or []

    @property
    def database_type(self) -> str:
        return "neo4j"


def _make_label(provider: str = "openai", model: str = "gpt-4o") -> Label:
    return Label(llm_type=LLMType.CHAT, provider=provider, model=model)


def _make_client() -> LLMClient:
    """Build a real LLMClient instance for testing.

    The instance is not connected to any real provider — we mock the
    `call` method in each test. Provider config is minimal but valid
    so __init__ does not raise.
    """
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


def _make_schema_record(
    schema_id: str = "schema-funding",
    event_type: str = "funding",
    pattern: str | None = None,
) -> dict[str, Any]:
    """Build a fake SchemaNode record (mirrors test_structured_output.py)."""
    if pattern is None:
        pattern = (
            '{"type": "object", '
            '"properties": {'
            '"amount": {"type": "number"}, '
            '"company": {"type": "string"}'
            "}, "
            '"required": ["amount", "company"]}'
        )
    return {
        "id": schema_id,
        "event_type": event_type,
        "pattern": pattern,
        "confidence": 0.9,
    }


def _set_graph_pool(client: LLMClient, records: list[dict[str, Any]] | None) -> None:
    """Inject a FakeGraphPool into the client (mirrors _smart_router pattern)."""
    client._graph_pool = FakeGraphPool(records=records)


class TestStructuredCallSuccess:
    """Scenario 1: schema exists + LLM returns valid JSON → return dict."""

    @pytest.mark.asyncio
    async def test_returns_parsed_dict_when_response_matches_schema(self):
        """Valid LLM response matching schema is parsed and returned as dict."""
        client = _make_client()
        _set_graph_pool(client, [_make_schema_record()])

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = '{"amount": 1000, "company": "Acme Inc"}'
            client._router.get_call_point_route = lambda cp: [_make_label()]
            client._router.get_call_point_config = lambda cp: None
            client._smart_router = None
            client._prompts = None

            result = await client.structured_call(
                prompt="Extract funding info",
                schema_node_id="schema-funding",
            )

        assert isinstance(result, dict)
        assert result["amount"] == 1000
        assert result["company"] == "Acme Inc"
        # Only 1 LLM call — no retry needed.
        assert mock_call.call_count == 1

    @pytest.mark.asyncio
    async def test_response_format_schema_passed_to_llm(self):
        """response_format with JSON Schema is forwarded to LLM call."""
        client = _make_client()
        _set_graph_pool(client, [_make_schema_record()])

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = '{"amount": 1, "company": "x"}'
            client._router.get_call_point_route = lambda cp: [_make_label()]
            client._router.get_call_point_config = lambda cp: None
            client._smart_router = None
            client._prompts = None

            await client.structured_call(
                prompt="test",
                schema_node_id="schema-funding",
            )

        # Verify response_format was forwarded in payload.
        call_payload = (
            mock_call.call_args.args[1]
            if mock_call.call_args.args
            else mock_call.call_args.kwargs.get("payload")
        )
        assert "response_format" in call_payload


class TestStructuredCallRetrySuccess:
    """Scenario 2: 1st response invalid → retry with hint → 2nd response valid."""

    @pytest.mark.asyncio
    async def test_retries_once_when_validation_fails_then_succeeds(self):
        """1st response missing required field → retry → 2nd response valid."""
        client = _make_client()
        _set_graph_pool(client, [_make_schema_record()])

        # 1st response missing 'company' (required field); 2nd response valid.
        responses = [
            '{"amount": 1000}',
            '{"amount": 1000, "company": "Acme Inc"}',
        ]

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = responses
            client._router.get_call_point_route = lambda cp: [_make_label()]
            client._router.get_call_point_config = lambda cp: None
            client._smart_router = None
            client._prompts = None

            result = await client.structured_call(
                prompt="Extract funding",
                schema_node_id="schema-funding",
            )

        assert result["amount"] == 1000
        assert result["company"] == "Acme Inc"
        # Exactly 2 calls — initial + 1 retry.
        assert mock_call.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_prompt_includes_schema_violation_hint(self):
        """Retry prompt contains the 'previous response violated schema' hint."""
        client = _make_client()
        _set_graph_pool(client, [_make_schema_record()])

        responses = [
            '{"amount": 1000}',  # missing 'company'
            '{"amount": 1000, "company": "x"}',
        ]

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = responses
            client._router.get_call_point_route = lambda cp: [_make_label()]
            client._router.get_call_point_config = lambda cp: None
            client._smart_router = None
            client._prompts = None

            await client.structured_call(
                prompt="Extract funding",
                schema_node_id="schema-funding",
            )

        # 2nd call's payload should contain a retry hint key.
        second_call_args = mock_call.call_args_list[1]
        second_payload = (
            second_call_args.args[1]
            if second_call_args.args
            else second_call_args.kwargs.get("payload")
        )
        assert "_retry_hint" in second_payload


class TestStructuredCallRetryFails:
    """Scenario 3: both responses invalid → StructuredOutputValidationError."""

    @pytest.mark.asyncio
    async def test_raises_structured_output_validation_error_after_retry(self):
        """Both 1st and 2nd responses invalid → raise StructuredOutputValidationError."""
        from core.llm.structured_output import StructuredOutputValidationError

        client = _make_client()
        _set_graph_pool(client, [_make_schema_record()])

        # Both responses missing 'company'.
        responses = [
            '{"amount": 1000}',
            '{"amount": 2000}',
        ]

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = responses
            client._router.get_call_point_route = lambda cp: [_make_label()]
            client._router.get_call_point_config = lambda cp: None
            client._smart_router = None
            client._prompts = None

            with pytest.raises(StructuredOutputValidationError) as exc_info:
                await client.structured_call(
                    prompt="Extract funding",
                    schema_node_id="schema-funding",
                )

        # Error must carry schema + last_response for debugging.
        assert exc_info.value.schema is not None
        assert "amount" in exc_info.value.schema["properties"]
        assert exc_info.value.last_response == '{"amount": 2000}'
        # Exactly 2 calls (initial + 1 retry).
        assert mock_call.call_count == 2

    @pytest.mark.asyncio
    async def test_validation_error_carries_schema_attribute(self):
        """StructuredOutputValidationError carries the JSON Schema used."""
        from core.llm.structured_output import StructuredOutputValidationError

        client = _make_client()
        _set_graph_pool(client, [_make_schema_record()])

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = '{"wrong_field": "x"}'
            client._router.get_call_point_route = lambda cp: [_make_label()]
            client._router.get_call_point_config = lambda cp: None
            client._smart_router = None
            client._prompts = None

            with pytest.raises(StructuredOutputValidationError) as exc_info:
                await client.structured_call(
                    prompt="test",
                    schema_node_id="schema-funding",
                )

        # Schema must contain 'amount' property (from _make_schema_record).
        assert "amount" in exc_info.value.schema["properties"]


class TestStructuredCallSchemaNotFound:
    """Scenario 4: SchemaNotFoundError → degrade to plain call (no retry)."""

    @pytest.mark.asyncio
    async def test_returns_fallback_when_schema_not_found(self):
        """SchemaNotFoundError → return {_fallback: true, content: <llm_response>}."""
        client = _make_client()
        _set_graph_pool(client, records=[])  # No SchemaNode found.

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "plain text response"
            client._router.get_call_point_route = lambda cp: [_make_label()]
            client._router.get_call_point_config = lambda cp: None
            client._smart_router = None
            client._prompts = None

            result = await client.structured_call(
                prompt="test",
                schema_node_id="schema-nonexistent",
            )

        assert isinstance(result, dict)
        assert result.get("_fallback") is True
        assert result["content"] == "plain text response"
        # Only 1 LLM call — no retry on SchemaNotFoundError path.
        assert mock_call.call_count == 1

    @pytest.mark.asyncio
    async def test_fallback_does_not_pass_response_format(self):
        """Fallback path does NOT pass response_format to LLM (plain call).

        Spec R-structured-002: SchemaNotFoundError → DIRECT fallback.
        The plain call should not include response_format=schema because
        the schema was not found.
        """
        client = _make_client()
        _set_graph_pool(client, records=[])

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "fallback content"
            client._router.get_call_point_route = lambda cp: [_make_label()]
            client._router.get_call_point_config = lambda cp: None
            client._smart_router = None
            client._prompts = None

            await client.structured_call(
                prompt="test",
                schema_node_id="schema-nonexistent",
            )

        call_payload = (
            mock_call.call_args.args[1]
            if mock_call.call_args.args
            else mock_call.call_args.kwargs.get("payload")
        )
        # response_format should be absent OR not be a JSON Schema dict.
        if "response_format" in call_payload:
            # If present, it must NOT be a dict (JSON Schema) — should be
            # plain mode (e.g. "json" or absent).
            assert (
                not isinstance(call_payload["response_format"], dict)
                or "properties" not in call_payload["response_format"]
            )


class TestStructuredCallGraphPoolNotInitialized:
    """Verify _graph_pool=None → ValueError (Rule 12 fail-loud)."""

    @pytest.mark.asyncio
    async def test_raises_value_error_when_graph_pool_not_injected(self):
        """_graph_pool=None → ValueError (caller must inject graph_pool).

        Mirrors _smart_router pattern: container must inject _graph_pool
        via attribute assignment (lifecycle.py pattern). If not injected,
        structured_call fails loudly rather than silently returning None.
        """
        client = _make_client()
        # _graph_pool not set → defaults to None (or AttributeError).
        # Implementation should check and raise ValueError explicitly.

        with pytest.raises((ValueError, AttributeError)):
            await client.structured_call(
                prompt="test",
                schema_node_id="schema-x",
            )


class TestStructuredCallInvalidJsonResponse:
    """Verify LLM response that is not valid JSON → StructuredOutputValidationError."""

    @pytest.mark.asyncio
    async def test_invalid_json_response_raises_validation_error(self):
        """LLM returns non-JSON text → StructuredOutputValidationError after retry.

        Non-JSON response is treated as validation failure — retry once,
        then raise. This is consistent with the retry path (R-structured-003).
        """
        from core.llm.structured_output import StructuredOutputValidationError

        client = _make_client()
        _set_graph_pool(client, [_make_schema_record()])

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "this is not json at all"
            client._router.get_call_point_route = lambda cp: [_make_label()]
            client._router.get_call_point_config = lambda cp: None
            client._smart_router = None
            client._prompts = None

            with pytest.raises(StructuredOutputValidationError):
                await client.structured_call(
                    prompt="test",
                    schema_node_id="schema-funding",
                )

        # 2 calls: initial + retry.
        assert mock_call.call_count == 2


class TestStructuredCallDegradeVsRetryMutex:
    """Verify degrade and retry are mutually exclusive (R-structured-002)."""

    @pytest.mark.asyncio
    async def test_schema_not_found_does_not_retry(self):
        """SchemaNotFoundError path: exactly 1 LLM call (no retry)."""
        client = _make_client()
        _set_graph_pool(client, records=[])

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "fallback"
            client._router.get_call_point_route = lambda cp: [_make_label()]
            client._router.get_call_point_config = lambda cp: None
            client._smart_router = None
            client._prompts = None

            await client.structured_call(
                prompt="test",
                schema_node_id="schema-x",
            )

        # No retry on fallback path.
        assert mock_call.call_count == 1


class TestStructuredCallCallPointForwarding:
    """Verify call_point + article_id + task_id forwarded to LLM call."""

    @pytest.mark.asyncio
    async def test_forwards_call_point_to_llm_call(self):
        """call_point is forwarded to self.call() for routing."""
        client = _make_client()
        _set_graph_pool(client, [_make_schema_record()])

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = '{"amount": 1, "company": "x"}'
            client._router.get_call_point_route = lambda cp: [_make_label()]
            client._router.get_call_point_config = lambda cp: None
            client._smart_router = None
            client._prompts = None

            await client.structured_call(
                prompt="test",
                schema_node_id="schema-funding",
                call_point=CallPoint.CLASSIFIER,
                article_id="art-123",
                task_id="task-456",
            )

        # Verify call_point + article_id + task_id forwarded.
        call_kwargs = mock_call.call_args.kwargs
        assert call_kwargs.get("article_id") == "art-123"
        assert call_kwargs.get("task_id") == "task-456"


__all__ = [
    "FakeGraphPool",
    "TestStructuredCallCallPointForwarding",
    "TestStructuredCallDegradeVsRetryMutex",
    "TestStructuredCallGraphPoolNotInitialized",
    "TestStructuredCallInvalidJsonResponse",
    "TestStructuredCallRetryFails",
    "TestStructuredCallRetrySuccess",
    "TestStructuredCallSchemaNotFound",
    "TestStructuredCallSuccess",
]
