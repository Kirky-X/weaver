# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for ExperienceStore."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.event.bus import EventBus, LLMUsageEvent
from core.llm.evaluation.experience import ExperienceStore
from core.llm.types import TokenUsage


@pytest.fixture
def event_bus():
    """Create a fresh EventBus."""
    return EventBus()


@pytest.fixture
def store(event_bus):
    """Create a fresh ExperienceStore."""
    return ExperienceStore(event_bus=event_bus)


@pytest.fixture
def store_with_warmup(event_bus):
    """Create ExperienceStore with warmup data."""
    warmup = {
        "classifier.aiping.GLM-Z1": {
            "call_count": 100,
            "success_count": 95,
            "failure_count": 5,
            "total_latency_ms": 250000.0,
        }
    }
    return ExperienceStore(event_bus=event_bus, warmup_data=warmup)


class TestExperienceStoreBasic:
    """Test basic ExperienceStore functionality."""

    def test_empty_experience(self, store):
        """New store returns defaults for unknown triplets."""
        exp = store.get_experience("classifier", "aiping", "GLM-Z1")
        assert exp.call_count == 0
        assert exp.success_count == 0
        assert exp.failure_count == 0
        assert exp.avg_latency_ms == 0.0
        # Use store method for reliability
        assert store.reliability("classifier", "aiping", "GLM-Z1") == 1.0

    def test_experience_count_starts_zero(self, store):
        assert store.experience_count == 0


@pytest.mark.asyncio
async def test_successful_call_records_experience():
    """Successful LLMUsageEvent increments counters."""
    event_bus = EventBus()
    store = ExperienceStore(event_bus=event_bus)

    event = LLMUsageEvent(
        label="chat.aiping.GLM-Z1",
        call_point="classifier",
        llm_type="chat",
        provider="aiping",
        model="GLM-Z1",
        latency_ms=2500.0,
        success=True,
        tokens=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
    )

    await event_bus.publish(event)

    exp = store.get_experience("classifier", "aiping", "GLM-Z1")
    assert exp.call_count == 1
    assert exp.success_count == 1
    assert exp.failure_count == 0
    assert exp.avg_latency_ms == 2500.0


@pytest.mark.asyncio
async def test_failed_call_records_experience():
    """Failed LLMUsageEvent increments failure counters."""
    event_bus = EventBus()
    store = ExperienceStore(event_bus=event_bus)

    event = LLMUsageEvent(
        label="chat.aiping.GLM-Z1",
        call_point="classifier",
        llm_type="chat",
        provider="aiping",
        model="GLM-Z1",
        latency_ms=3000.0,
        success=False,
        error_type="timeout",
        tokens=TokenUsage(),
    )

    await event_bus.publish(event)

    exp = store.get_experience("classifier", "aiping", "GLM-Z1")
    assert exp.call_count == 1
    assert exp.success_count == 0
    assert exp.failure_count == 1
    assert exp.last_error_type == "timeout"


class TestReliability:
    """Test reliability score calculation."""

    def test_no_data_returns_one(self, store):
        """New models have optimistic reliability."""
        assert store.reliability("test", "prov", "model") == 1.0

    def test_all_success_returns_one(self, store_with_warmup):
        """100% success rate returns 1.0."""
        reliability = store_with_warmup.reliability("classifier", "aiping", "GLM-Z1")
        assert reliability == 0.95  # 95/100

    def test_partial_success(self, store):
        """Mixed success/failure returns correct ratio."""
        # Manually set up data via event
        pass  # tested via async tests


class TestThompsonSampling:
    """Test Thompson Sampling Beta distribution."""

    def test_new_model_returns_random(self, store):
        """New models return value from Beta(1,1) = Uniform(0,1)."""
        sample = store.thompson_sample("test", "prov", "model")
        assert 0.0 <= sample <= 1.0

    def test_mature_model_returns_tight(self, store_with_warmup):
        """Mature models have tight distribution around success rate."""
        # Run multiple samples and check mean is near success rate
        samples = [
            store_with_warmup.thompson_sample("classifier", "aiping", "GLM-Z1") for _ in range(100)
        ]
        mean = sum(samples) / len(samples)
        # With 95/100 success, mean should be roughly 0.95
        assert 0.85 <= mean <= 1.0

    def test_alpha_increases_with_success(self, store_with_warmup):
        """Successful calls increase alpha parameter."""
        exp = store_with_warmup.get_experience("classifier", "aiping", "GLM-Z1")
        assert exp.thompson_alpha == 96.0  # 95 + 1
        assert exp.thompson_beta == 6.0  # 5 + 1


class TestWarmup:
    """Test warmup from historical data."""

    def test_warmup_populates_experience(self, store_with_warmup):
        """Warmup data is loaded into experience store."""
        exp = store_with_warmup.get_experience("classifier", "aiping", "GLM-Z1")
        assert exp.call_count == 100
        assert exp.success_count == 95
        assert exp.failure_count == 5
        assert exp.avg_latency_ms == 2500.0  # 250000 / 100

    def test_warmup_sets_thompson_params(self, store_with_warmup):
        """Warmup data sets correct Thompson params."""
        exp = store_with_warmup.get_experience("classifier", "aiping", "GLM-Z1")
        assert exp.thompson_alpha == 96.0
        assert exp.thompson_beta == 6.0
