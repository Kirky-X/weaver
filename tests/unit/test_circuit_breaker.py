"""Unit tests for CircuitBreaker."""

import asyncio

import pytest
import time

from core.resilience.circuit_breaker import CircuitBreaker, CBState


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    @pytest.mark.asyncio
    async def test_initial_state_closed(self):
        """Test circuit breaker starts in closed state."""
        cb = CircuitBreaker()
        assert cb.state == CBState.CLOSED
        assert cb._fail_count == 0

    def test_is_open_returns_false_when_closed(self):
        """Test is_open returns False when circuit is closed."""
        cb = CircuitBreaker()
        assert cb.is_open() is False

    @pytest.mark.asyncio
    async def test_threshold_triggers_open(self):
        """Test reaching threshold triggers open state."""
        cb = CircuitBreaker(threshold=3, timeout_secs=60.0)
        await cb.record_failure()
        await cb.record_failure()
        assert cb.state == CBState.CLOSED
        await cb.record_failure()
        assert cb.state == CBState.OPEN

    @pytest.mark.asyncio
    async def test_is_open_returns_true_when_open(self):
        """Test is_open returns True when circuit is open."""
        cb = CircuitBreaker(threshold=2, timeout_secs=60.0)
        await cb.record_failure()
        await cb.record_failure()
        assert cb.is_open() is True

    @pytest.mark.asyncio
    async def test_timeout_transitions_to_half_open(self):
        """Test timeout transitions circuit to half-open state."""
        cb = CircuitBreaker(threshold=1, timeout_secs=0.1)
        await cb.record_failure()
        assert cb.state == CBState.OPEN
        await asyncio.sleep(0.15)
        cb.is_open()  # Trigger the transition
        assert cb.state == CBState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_success_closes(self):
        """Test success in half-open state closes circuit."""
        cb = CircuitBreaker(threshold=1, timeout_secs=0.1)
        await cb.record_failure()
        await asyncio.sleep(0.15)
        cb.is_open()  # Trigger the transition
        assert cb.state == CBState.HALF_OPEN
        await cb.record_success()
        assert cb.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_opens(self):
        """Test failure in half-open state opens circuit."""
        cb = CircuitBreaker(threshold=1, timeout_secs=0.1)
        await cb.record_failure()
        await asyncio.sleep(0.15)
        cb.is_open()  # Trigger the transition
        assert cb.state == CBState.HALF_OPEN
        await cb.record_failure()
        assert cb.state == CBState.OPEN

    @pytest.mark.asyncio
    async def test_record_success_resets_count(self):
        """Test recording success resets failure count."""
        cb = CircuitBreaker(threshold=5)
        await cb.record_failure()
        await cb.record_failure()
        await cb.record_failure()
        assert cb._fail_count == 3
        await cb.record_success()
        assert cb._fail_count == 0
        assert cb.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_reset_method(self):
        """Test manual reset functionality."""
        cb = CircuitBreaker(threshold=1, timeout_secs=60.0)
        await cb.record_failure()
        assert cb.state == CBState.OPEN
        await cb.reset()
        assert cb.state == CBState.CLOSED
        assert cb._fail_count == 0
        assert cb._opened_at == 0.0

    @pytest.mark.asyncio
    async def test_custom_threshold(self):
        """Test custom threshold value."""
        cb = CircuitBreaker(threshold=10)
        for _ in range(9):
            await cb.record_failure()
        assert cb.state == CBState.CLOSED
        await cb.record_failure()
        assert cb.state == CBState.OPEN

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        """Test custom timeout value."""
        cb = CircuitBreaker(threshold=1, timeout_secs=0.05)
        await cb.record_failure()
        assert cb.state == CBState.OPEN
        await asyncio.sleep(0.1)
        cb.is_open()  # Trigger the transition
        assert cb.state == CBState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_multiple_failures_after_reset(self):
        """Test circuit breaker works correctly after reset."""
        cb = CircuitBreaker(threshold=2)
        await cb.record_failure()
        await cb.record_failure()
        assert cb.state == CBState.OPEN
        await cb.reset()
        await cb.record_failure()
        assert cb.state == CBState.CLOSED
        await cb.record_failure()
        assert cb.state == CBState.OPEN

    @pytest.mark.asyncio
    async def test_state_property_transitions(self):
        """Test state property handles OPEN to HALF_OPEN transition."""
        cb = CircuitBreaker(threshold=1, timeout_secs=0.05)
        await cb.record_failure()
        assert cb.state == CBState.OPEN
        await asyncio.sleep(0.1)
        cb.is_open()  # Trigger the transition
        assert cb.state == CBState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_consecutive_failures_dont_exceed_threshold(self):
        """Test failures beyond threshold don't change state."""
        cb = CircuitBreaker(threshold=2)
        await cb.record_failure()
        await cb.record_failure()
        assert cb.state == CBState.OPEN
        await cb.record_failure()
        await cb.record_failure()
        assert cb.state == CBState.OPEN
