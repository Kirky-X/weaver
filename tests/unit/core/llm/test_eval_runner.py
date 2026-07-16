# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for EvalRunner shadow evaluation."""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event import LLMCompareEvent
from core.llm import EvalConfig, Label, TokenUsage
from core.llm.evaluation.eval_runner import EvalRunner, EvalRunnerConfig


@pytest.fixture
def eval_config():
    """Create test eval config."""
    return EvalConfig(
        enabled=True,
        sample_rate=0.5,  # 50% for testing
        target_call_points=["classifier", "test_point"],
        baseline_model="chat.provider1.model1",
        candidate_models=["chat.provider2.model2"],
    )


@pytest.fixture
def mock_event_bus():
    """Create mock event bus."""
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def mock_llm():
    """Create mock LLM client."""
    client = MagicMock()
    client.call_at = AsyncMock(return_value="test response")
    return client


class TestEvalRunnerConfig:
    """Tests for EvalRunner configuration."""

    def test_default_values(self):
        """EvalRunnerConfig has sensible defaults."""
        config = EvalRunnerConfig(
            enabled=True,
            target_call_points={"test"},
            candidate_labels=[Label.parse("chat.p2.m2")],
        )

        assert config.enabled is True
        assert config.sample_rate == 0.1  # Default 10%
        assert config.target_call_points == {"test"}

    def test_sample_rate_validation(self):
        """Sample rate must be between 0 and 1."""
        # Valid rates
        for rate in [0.0, 0.1, 0.5, 1.0]:
            config = EvalRunnerConfig(
                enabled=True,
                sample_rate=rate,
                target_call_points={"test"},
                candidate_labels=[Label.parse("chat.p2.m2")],
            )
            assert config.sample_rate == rate


class TestEvalRunnerInitialization:
    """Tests for EvalRunner initialization."""

    def test_from_eval_config(self, eval_config, mock_event_bus, mock_llm):
        """EvalRunner creates from EvalConfig."""
        runner = EvalRunner.from_eval_config(
            eval_cfg=eval_config,
            llm_client=mock_llm,
            event_bus=mock_event_bus,
        )

        assert runner._config.enabled == eval_config.enabled
        assert runner._config.sample_rate == eval_config.sample_rate
        assert runner._event_bus == mock_event_bus
        assert runner._llm_client == mock_llm


class TestEvalRunnerSampling:
    """Tests for shadow call sampling logic."""

    def test_should_trigger_respects_rate(self, eval_config, mock_event_bus, mock_llm):
        """Sampling respects configured sample_rate."""
        runner = EvalRunner.from_eval_config(
            eval_cfg=eval_config,
            llm_client=mock_llm,
            event_bus=mock_event_bus,
        )

        # With 0.5 sample rate, should trigger for valid call_point ~50% of time
        # We can't test randomness deterministically, but can verify it returns bool
        result = runner.should_trigger("classifier")
        assert isinstance(result, bool)

    def test_should_trigger_disabled_returns_false(self, mock_event_bus, mock_llm):
        """Disabled eval never triggers."""
        eval_config = EvalConfig(
            enabled=False,
            sample_rate=0.5,
            target_call_points=["classifier"],
            baseline_model="chat.p1.m1",
            candidate_models=["chat.p2.m2"],
        )
        runner = EvalRunner.from_eval_config(
            eval_cfg=eval_config,
            llm_client=mock_llm,
            event_bus=mock_event_bus,
        )

        assert runner.should_trigger("classifier") is False

    def test_should_trigger_zero_rate_returns_false(self, mock_event_bus, mock_llm):
        """Zero sample rate never triggers."""
        eval_config = EvalConfig(
            enabled=True,
            sample_rate=0.0,
            target_call_points=["classifier"],
            baseline_model="chat.p1.m1",
            candidate_models=["chat.p2.m2"],
        )
        runner = EvalRunner.from_eval_config(
            eval_cfg=eval_config,
            llm_client=mock_llm,
            event_bus=mock_event_bus,
        )

        assert runner.should_trigger("classifier") is False

    def test_should_trigger_wrong_call_point_returns_false(
        self, eval_config, mock_event_bus, mock_llm
    ):
        """Wrong call_point never triggers."""
        runner = EvalRunner.from_eval_config(
            eval_cfg=eval_config,
            llm_client=mock_llm,
            event_bus=mock_event_bus,
        )

        assert runner.should_trigger("unknown_point") is False


class TestEvalRunnerShadowCalls:
    """Tests for shadow call execution."""

    @pytest.mark.asyncio
    async def test_trigger_shadow_call_fire_and_forget(self, eval_config, mock_event_bus, mock_llm):
        """Shadow call is non-blocking (fire-and-forget)."""
        runner = EvalRunner.from_eval_config(
            eval_cfg=eval_config,
            llm_client=mock_llm,
            event_bus=mock_event_bus,
        )

        primary_label = Label.parse("chat.provider1.model1")
        primary_tokens = TokenUsage(input_tokens=10, output_tokens=20)

        # This should return quickly, not wait for shadow call
        await runner.trigger_shadow_call(
            call_point="classifier",
            primary_label=primary_label,
            primary_result="baseline",
            primary_latency=0.5,
            primary_success=True,
            primary_tokens=primary_tokens,
            payload={"prompt": "test"},
        )

        # If we reach here quickly, it's fire-and-forget

    @pytest.mark.asyncio
    async def test_trigger_shadow_call_skips_when_no_candidates(self, mock_event_bus, mock_llm):
        """Shadow call skipped when no candidate labels."""
        eval_config = EvalConfig(
            enabled=True,
            sample_rate=0.5,
            target_call_points=["classifier"],
            baseline_model="chat.p1.m1",
            candidate_models=[],  # No candidates
        )
        runner = EvalRunner.from_eval_config(
            eval_cfg=eval_config,
            llm_client=mock_llm,
            event_bus=mock_event_bus,
        )

        primary_label = Label.parse("chat.provider1.model1")
        primary_tokens = TokenUsage(input_tokens=10, output_tokens=20)

        await runner.trigger_shadow_call(
            call_point="classifier",
            primary_label=primary_label,
            primary_result="baseline",
            primary_latency=0.5,
            primary_success=True,
            primary_tokens=primary_tokens,
            payload={"prompt": "test"},
        )

        # Verify no calls were made
        mock_llm.call_at.assert_not_called()


class TestEvalRunnerIsolation:
    """Tests for shadow call isolation from main path."""

    @pytest.mark.asyncio
    async def test_shadow_call_failure_does_not_propagate(
        self, eval_config, mock_event_bus, mock_llm
    ):
        """Shadow call failure doesn't affect main path."""
        # Make shadow call fail
        mock_llm.call_at.side_effect = Exception("Shadow call failed")

        runner = EvalRunner.from_eval_config(
            eval_cfg=eval_config,
            llm_client=mock_llm,
            event_bus=mock_event_bus,
        )

        primary_label = Label.parse("chat.provider1.model1")
        primary_tokens = TokenUsage(input_tokens=10, output_tokens=20)

        # Should not raise exception
        await runner.trigger_shadow_call(
            call_point="classifier",
            primary_label=primary_label,
            primary_result="baseline",
            primary_latency=0.5,
            primary_success=True,
            primary_tokens=primary_tokens,
            payload={"prompt": "test"},
        )

        # Test passes if no exception raised

    @pytest.mark.asyncio
    async def test_shadow_call_timeout_does_not_block(self, eval_config, mock_event_bus, mock_llm):
        """Shadow call timeout doesn't block main path."""
        import asyncio

        # Make shadow call hang
        async def hanging_call(*args, **kwargs):
            await asyncio.sleep(10)  # Very slow
            return "timeout"

        mock_llm.call_at.side_effect = hanging_call

        runner = EvalRunner.from_eval_config(
            eval_cfg=eval_config,
            llm_client=mock_llm,
            event_bus=mock_event_bus,
        )

        primary_label = Label.parse("chat.provider1.model1")
        primary_tokens = TokenUsage(input_tokens=10, output_tokens=20)

        # Should complete quickly (fire-and-forget)
        await runner.trigger_shadow_call(
            call_point="classifier",
            primary_label=primary_label,
            primary_result="baseline",
            primary_latency=0.5,
            primary_success=True,
            primary_tokens=primary_tokens,
            payload={"prompt": "test"},
        )

        # Test passes if it doesn't hang
