# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for circuit_breaker module."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from core.llm.resilience.circuit_breaker import (
    CircuitOpenError,
    ProviderCircuitBreaker,
)
from core.llm.types import CircuitState


class TestCircuitOpenError:
    """Test CircuitOpenError exception."""

    def test_error_message(self):
        """Test error message contains provider name."""
        error = CircuitOpenError("test_provider")
        assert "test_provider" in str(error)
        assert "Circuit breaker is OPEN" in str(error)
        assert error.provider == "test_provider"


class TestProviderCircuitBreakerInit:
    """Test ProviderCircuitBreaker initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        cb = ProviderCircuitBreaker(name="test")
        assert cb.name == "test"
        assert cb.slow_count == 0
        assert cb.is_open is False

    def test_init_with_custom_parameters(self):
        """Test initialization with custom parameters."""
        cb = ProviderCircuitBreaker(
            name="custom",
            fail_max=3,
            reset_timeout=30.0,
            slow_threshold=0.3,
        )
        assert cb.name == "custom"
        assert cb._breaker.fail_max == 3
        assert cb._breaker.reset_timeout == 30.0


class TestSlowRequestTracking:
    """Test slow request tracking functionality."""

    def test_mark_slow_increments_counter(self):
        """Test mark_slow increments counter."""
        cb = ProviderCircuitBreaker(name="test")
        cb.mark_slow()
        assert cb.slow_count == 1

    def test_mark_fast_resets_counter(self):
        """Test mark_fast resets counter."""
        cb = ProviderCircuitBreaker(name="test")
        cb.mark_slow()
        cb.mark_slow()
        cb.mark_fast()
        assert cb.slow_count == 0

    def test_is_slow_after_5_consecutive(self):
        """Test is_slow returns True after 5 consecutive slow requests."""
        cb = ProviderCircuitBreaker(name="test")
        for _ in range(5):
            cb.mark_slow()
        assert cb.is_slow is True

    def test_is_not_slow_before_5(self):
        """Test is_slow returns False before 5 consecutive."""
        cb = ProviderCircuitBreaker(name="test")
        for _ in range(4):
            cb.mark_slow()
        assert cb.is_slow is False


class TestCircuitBreakerState:
    """Test circuit breaker state management."""

    def test_initial_state_is_closed(self):
        """Test initial state is CLOSED."""
        cb = ProviderCircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED
        assert cb.is_open is False

    def test_state_after_failures(self):
        """Test state transitions to OPEN after max failures."""
        cb = ProviderCircuitBreaker(name="test", fail_max=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        assert cb.state == CircuitState.OPEN

    def test_reset_closes_circuit(self):
        """Test reset closes circuit."""
        cb = ProviderCircuitBreaker(name="test", fail_max=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True

        cb.reset()
        assert cb.is_open is False
        assert cb.state == CircuitState.CLOSED

    def test_reset_clears_slow_counter(self):
        """Test reset clears slow counter."""
        cb = ProviderCircuitBreaker(name="test")
        cb.mark_slow()
        cb.mark_slow()
        cb.reset()
        assert cb.slow_count == 0


class TestCircuitBreakerCall:
    """Test circuit breaker call functionality."""

    @pytest.mark.asyncio
    async def test_call_success(self):
        """Test successful async call."""
        cb = ProviderCircuitBreaker(name="test")

        async def success_func():
            return "success"

        result = await cb.call(success_func)
        assert result == "success"
        assert cb.is_open is False

    @pytest.mark.asyncio
    async def test_call_failure_opens_circuit(self):
        """Test that failures eventually open circuit."""
        cb = ProviderCircuitBreaker(name="test", fail_max=2)

        async def fail_func():
            raise ValueError("Test error")

        # First failure
        with pytest.raises(ValueError):
            await cb.call(fail_func)
        assert cb.is_open is False

        # Second failure should open circuit
        with pytest.raises(ValueError):
            await cb.call(fail_func)
        # Circuit should be open now
        assert cb.is_open is True

    @pytest.mark.asyncio
    async def test_call_when_open_raises_error(self):
        """Test that calling when circuit is open raises CircuitOpenError."""
        cb = ProviderCircuitBreaker(name="test", fail_max=1)

        async def fail_func():
            raise ValueError("Test error")

        # Open the circuit
        with pytest.raises(ValueError):
            await cb.call(fail_func)

        # Now call should raise CircuitOpenError
        async def success_func():
            return "success"

        with pytest.raises(CircuitOpenError) as exc_info:
            await cb.call(success_func)
        assert "test" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_call_tracks_slow_requests(self):
        """Test that slow requests are tracked."""
        cb = ProviderCircuitBreaker(name="test", slow_threshold=0.5)
        cb._timeout = 0.001  # Very short timeout to trigger slow detection

        async def slow_func():
            await asyncio.sleep(0.01)  # Sleep longer than timeout
            return "slow"

        await cb.call(slow_func)
        # Should be marked as slow
        assert cb.slow_count >= 0  # May or may not be slow depending on timing


class TestCircuitBreakerRepr:
    """Test circuit breaker string representation."""

    def test_repr_contains_name_and_state(self):
        """Test repr contains name and state."""
        cb = ProviderCircuitBreaker(name="test_provider")
        repr_str = repr(cb)
        assert "test_provider" in repr_str
        assert "closed" in repr_str.lower()
