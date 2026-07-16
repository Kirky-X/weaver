# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for circuit breaker slow request tracking."""

import pytest

from core.llm import CircuitState
from core.llm.resilience.circuit_breaker import (
    CircuitOpenError,
    ProviderCircuitBreaker,
)


class TestCircuitBreakerSlowTracking:
    """Test slow request tracking in circuit breaker."""

    def test_initial_slow_count_is_zero(self):
        cb = ProviderCircuitBreaker(name="test")
        assert cb.slow_count == 0
        assert not cb.is_slow

    def test_mark_slow_increments_counter(self):
        cb = ProviderCircuitBreaker(name="test")
        for _ in range(5):
            cb.mark_slow()
        assert cb.slow_count == 5
        assert cb.is_slow

    def test_mark_fast_resets_counter(self):
        cb = ProviderCircuitBreaker(name="test")
        for _ in range(5):
            cb.mark_slow()
        cb.mark_fast()
        assert cb.slow_count == 0
        assert not cb.is_slow

    def test_five_consecutive_marks_as_slow(self):
        cb = ProviderCircuitBreaker(name="test")
        for _ in range(4):
            cb.mark_slow()
        assert not cb.is_slow  # 4 is not enough
        cb.mark_slow()
        assert cb.is_slow  # 5 triggers

    def test_reset_clears_slow_count(self):
        cb = ProviderCircuitBreaker(name="test")
        for _ in range(10):
            cb.mark_slow()
        cb.reset()
        assert cb.slow_count == 0

    def test_repr_includes_slow_count(self):
        cb = ProviderCircuitBreaker(name="test")
        cb.mark_slow()
        repr_str = repr(cb)
        assert "slow=1" in repr_str


class TestCircuitBreakerState:
    """Test circuit breaker state management."""

    def test_initial_state_is_closed(self):
        cb = ProviderCircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED
        assert not cb.is_open

    def test_reset_on_fresh_instance(self):
        cb = ProviderCircuitBreaker(name="test")
        cb.reset()
        assert cb.state == CircuitState.CLOSED
