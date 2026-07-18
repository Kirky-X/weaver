# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for LLMClient cost_usd integration (D2 / audit-unintegrated-modules).

Verifies that:
1. When a CostCalculator is wired, _emit_usage_event computes cost_usd
   from token_usage and passes it to LLMUsageEvent.
2. When CostCalculator is None (default), cost_usd stays 0.0 (backward compat).
3. When CostCalculator raises an exception, cost_usd degrades to 0.0 and
   the event is still published with a warning logged.
4. When token_usage is None, cost_usd stays 0.0 (no crash).
5. create_from_settings wires CostCalculator from llm_settings.cost.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.config import CostConfig, CostRate
from core.llm.cost.calculator import CostCalculator
from core.llm.types import (
    CallPoint,
    GlobalConfig,
    Label,
    LLMType,
    ProviderConfig,
    TokenUsage,
)


def _make_label(provider: str = "openai", model: str = "gpt-4o") -> Label:
    return Label(llm_type=LLMType.CHAT, provider=provider, model=model)


def _make_providers() -> list[ProviderConfig]:
    return [
        ProviderConfig(
            name="openai",
            type="openai",
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            rpm_limit=100,
            concurrency=5,
            timeout=30.0,
            priority=100,
            weight=100,
            models={},
        )
    ]


def _make_global_config() -> GlobalConfig:
    return GlobalConfig(
        circuit_breaker_threshold=5,
        circuit_breaker_timeout=60.0,
        default_timeout=120.0,
    )


def _make_event_bus() -> MagicMock:
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


def _make_client(cost_calculator: CostCalculator | None = None):
    from core.llm.client import LLMClient

    return LLMClient(
        providers=_make_providers(),
        global_config=_make_global_config(),
        event_bus=_make_event_bus(),
        cost_calculator=cost_calculator,
    )


def _make_cost_calculator() -> CostCalculator:
    """CostCalculator with a known rate for label 'chat.openai.gpt-4o'."""
    config = CostConfig(
        rates={
            "chat.openai.gpt-4o": CostRate(input=0.0025, output=0.01, cached=1.0),
        }
    )
    return CostCalculator(config=config)


@pytest.mark.asyncio
class TestLLMClientCostIntegration:
    """Verify D2: LLMClient._emit_usage_event integrates CostCalculator."""

    async def test_cost_calculator_wired_computes_cost_usd(self):
        """When CostCalculator is wired, cost_usd is computed and passed to event."""
        calc = _make_cost_calculator()
        client = _make_client(cost_calculator=calc)

        label = _make_label()
        tokens = TokenUsage(input_tokens=1000, output_tokens=500)

        await client._emit_usage_event(
            label=label,
            call_point=CallPoint.CLASSIFIER,
            latency_ms=200.0,
            token_usage=tokens,
            success=True,
        )

        client._event_bus.publish.assert_awaited_once()
        event = client._event_bus.publish.call_args.args[0]
        # input_cost = (1000/1000) * 0.0025 = 0.0025
        # cached_cost = 0
        # output_cost = (500/1000) * 0.01 = 0.005
        # total = 0.0075
        assert event.cost_usd == pytest.approx(0.0075, abs=1e-10)

    async def test_no_cost_calculator_keeps_zero(self):
        """When CostCalculator is None (default), cost_usd stays 0.0."""
        client = _make_client(cost_calculator=None)

        label = _make_label()
        tokens = TokenUsage(input_tokens=1000, output_tokens=500)

        await client._emit_usage_event(
            label=label,
            call_point=CallPoint.CLASSIFIER,
            latency_ms=200.0,
            token_usage=tokens,
            success=True,
        )

        client._event_bus.publish.assert_awaited_once()
        event = client._event_bus.publish.call_args.args[0]
        assert event.cost_usd == 0.0

    async def test_cost_calculator_exception_degrades_to_zero(self):
        """When CostCalculator raises, cost_usd degrades to 0.0 and event still publishes."""
        # Wire a calculator whose calculate() raises.
        calc = MagicMock(spec=CostCalculator)
        calc.calculate.side_effect = RuntimeError("boom")
        client = _make_client(cost_calculator=calc)

        label = _make_label()
        tokens = TokenUsage(input_tokens=1000, output_tokens=500)

        await client._emit_usage_event(
            label=label,
            call_point=CallPoint.CLASSIFIER,
            latency_ms=200.0,
            token_usage=tokens,
            success=True,
        )

        client._event_bus.publish.assert_awaited_once()
        event = client._event_bus.publish.call_args.args[0]
        assert event.cost_usd == 0.0

    async def test_none_token_usage_keeps_zero(self):
        """When token_usage is None, cost_usd stays 0.0 (no crash)."""
        calc = _make_cost_calculator()
        client = _make_client(cost_calculator=calc)

        label = _make_label()

        await client._emit_usage_event(
            label=label,
            call_point=CallPoint.CLASSIFIER,
            latency_ms=200.0,
            token_usage=None,
            success=True,
        )

        client._event_bus.publish.assert_awaited_once()
        event = client._event_bus.publish.call_args.args[0]
        assert event.cost_usd == 0.0

    async def test_default_constructor_has_no_cost_calculator(self):
        """LLMClient constructed without cost_calculator has _cost_calculator=None."""
        client = _make_client()
        assert client._cost_calculator is None

    async def test_cached_tokens_cost_applied(self):
        """Cached tokens are billed at the cached fraction of input rate."""
        config = CostConfig(
            rates={
                "chat.openai.gpt-4o": CostRate(input=0.0025, output=0.01, cached=0.5),
            }
        )
        calc = CostCalculator(config=config)
        client = _make_client(cost_calculator=calc)

        label = _make_label()
        # input=1000, cached=300, output=500
        # effective_input = 1000 - 300 = 700
        # input_cost = (700/1000) * 0.0025 = 0.00175
        # cached_cost = (300/1000) * 0.0025 * 0.5 = 0.000375
        # output_cost = (500/1000) * 0.01 = 0.005
        # total = 0.00175 + 0.000375 + 0.005 = 0.007125
        tokens = TokenUsage(input_tokens=1000, cached_tokens=300, output_tokens=500)

        await client._emit_usage_event(
            label=label,
            call_point=CallPoint.CLASSIFIER,
            latency_ms=200.0,
            token_usage=tokens,
            success=True,
        )

        event = client._event_bus.publish.call_args.args[0]
        assert event.cost_usd == pytest.approx(0.007125, abs=1e-10)


@pytest.mark.asyncio
class TestCreateFromSettingsWiresCostCalculator:
    """Verify create_from_settings instantiates and injects CostCalculator."""

    async def test_create_from_settings_wires_cost_calculator(self):
        """create_from_settings should instantiate CostCalculator from llm_settings.cost."""
        from core.llm.client import LLMClient

        # Build a minimal LLMSettings-like object with the cost field.
        # Using a MagicMock to avoid loading the full llm.toml.
        settings = MagicMock()
        settings.providers = {}
        settings.circuit_breaker_threshold = 5
        settings.circuit_breaker_timeout = 60.0
        settings.default_timeout = 120.0
        settings.defaults = {}
        settings.call_points = {}
        settings.cost = CostConfig(
            rates={
                "chat.openai.gpt-4o": CostRate(input=0.0025, output=0.01, cached=1.0),
            }
        )

        event_bus = _make_event_bus()
        client = await LLMClient.create_from_settings(
            llm_settings=settings,
            event_bus=event_bus,
        )

        # CostCalculator should be wired.
        assert client._cost_calculator is not None
        assert isinstance(client._cost_calculator, CostCalculator)

        # And it should produce non-zero cost for the configured label.
        label = _make_label()
        tokens = TokenUsage(input_tokens=1000, output_tokens=500)
        await client._emit_usage_event(
            label=label,
            call_point=CallPoint.CLASSIFIER,
            latency_ms=200.0,
            token_usage=tokens,
            success=True,
        )

        event = event_bus.publish.call_args.args[0]
        assert event.cost_usd == pytest.approx(0.0075, abs=1e-10)

    async def test_create_from_settings_default_empty_cost(self):
        """When llm_settings.cost has no rates, CostCalculator is None (MEDIUM-3 conditional init)."""
        from core.llm.client import LLMClient

        settings = MagicMock()
        settings.providers = {}
        settings.circuit_breaker_threshold = 5
        settings.circuit_breaker_timeout = 60.0
        settings.default_timeout = 120.0
        settings.defaults = {}
        settings.call_points = {}
        settings.cost = CostConfig()  # empty default — no rates

        event_bus = _make_event_bus()
        client = await LLMClient.create_from_settings(
            llm_settings=settings,
            event_bus=event_bus,
        )

        # MEDIUM-3: empty rates → cost_calculator is None (skip pointless compute)
        assert client._cost_calculator is None
        # cost_usd should be 0.0
        label = _make_label()
        tokens = TokenUsage(input_tokens=1000, output_tokens=500)
        await client._emit_usage_event(
            label=label,
            call_point=CallPoint.CLASSIFIER,
            latency_ms=200.0,
            token_usage=tokens,
            success=True,
        )

        event = event_bus.publish.call_args.args[0]
        assert event.cost_usd == 0.0
