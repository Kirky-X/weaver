# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for warmup_strategy = round_robin in ExperienceStore."""

from unittest.mock import MagicMock

import pytest

from core.llm.evaluation.experience import ExperienceStore


@pytest.fixture
def event_bus():
    """Create a mock EventBus."""
    bus = MagicMock()
    bus.subscribe = MagicMock()
    return bus


@pytest.fixture
def providers():
    """Return a list of provider identifiers for round-robin testing."""
    return ["provider_a", "provider_b", "provider_c"]


class TestRoundRobinDuringWarmup:
    """During warmup period, thompson_sample should use round-robin selection."""

    def test_round_robin_during_warmup(self, event_bus, providers):
        """First N calls cycle through providers in order."""
        store = ExperienceStore(event_bus=event_bus, warmup_calls=6)

        call_point = "classifier"
        model = "gpt-4"

        # During warmup, thompson_sample should return round-robin index
        # The store tracks a global warmup counter; each call increments it
        selections = []
        for _ in range(6):
            # select_provider returns the provider chosen by round-robin during warmup
            provider = store.select_provider(call_point, providers, model)
            selections.append(provider)

        # Should cycle: a, b, c, a, b, c
        expected = [
            "provider_a",
            "provider_b",
            "provider_c",
            "provider_a",
            "provider_b",
            "provider_c",
        ]
        assert selections == expected

    def test_thompson_sampling_after_warmup(self, event_bus, providers):
        """After warmup_calls, use Thompson Sampling instead of round-robin."""
        store = ExperienceStore(event_bus=event_bus, warmup_calls=3)

        call_point = "classifier"
        model = "gpt-4"

        # Exhaust warmup period
        for _ in range(3):
            store.select_provider(call_point, providers, model)

        # After warmup, thompson_sample should be used
        # We can verify by checking that selections are no longer strictly round-robin
        # With all equal experience, Thompson Sampling is random but valid
        post_warmup = []
        for _ in range(10):
            provider = store.select_provider(call_point, providers, model)
            post_warmup.append(provider)

        # All selections should be valid providers
        assert all(p in providers for p in post_warmup)
        # After warmup, the internal flag should indicate warmup is complete
        assert store.warmup_complete(call_point)

    def test_warmup_calls_default_20(self, event_bus):
        """Default warmup_calls = 20."""
        store = ExperienceStore(event_bus=event_bus)
        assert store._warmup_calls == 20

    def test_round_robin_cycles_through_all_providers(self, event_bus, providers):
        """Round-robin cycles through all providers in order."""
        store = ExperienceStore(event_bus=event_bus, warmup_calls=9)

        call_point = "classifier"
        model = "gpt-4"

        # 9 calls = 3 full cycles through 3 providers
        selections = []
        for _ in range(9):
            provider = store.select_provider(call_point, providers, model)
            selections.append(provider)

        # 3 full cycles: [a,b,c] * 3
        expected = ["provider_a", "provider_b", "provider_c"] * 3
        assert selections == expected
