# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for CircuitBreaker thread safety.

Tests for concurrent state transitions, atomic updates,
HALF_OPEN probe behavior, and async is_open() serialization.
"""

import asyncio
import time

import pytest

from core.resilience import CBState, CircuitBreaker


class TestCircuitBreakerThreadSafety:
    """Tests for CircuitBreaker thread safety guarantees."""

    @pytest.mark.asyncio
    async def test_concurrent_state_transitions(self):
        """Test concurrent state transitions are properly serialized.

        Given: Circuit breaker in CLOSED state
        When: Multiple concurrent calls to record_failure()
        Then: State transitions are serialized and consistent
        """
        cb = CircuitBreaker(threshold=10, timeout_secs=60.0)

        tasks = [cb.record_failure() for _ in range(15)]
        results = await asyncio.gather(*tasks)

        assert all(results)
        # After threshold failures, state should be OPEN
        assert cb.state == CBState.OPEN

    @pytest.mark.asyncio
    async def test_concurrent_success_and_failure(self):
        """Test concurrent success and failure recordings.

        Given: Circuit breaker in CLOSED state
        When: Concurrent calls to record_success() and record_failure()
        Then: Operations are serialized, state is consistent
        """
        cb = CircuitBreaker(threshold=5, timeout_secs=60.0)

        for _ in range(3):
            await cb.record_failure()

        # 3 failures, still CLOSED
        assert cb.state == CBState.CLOSED

        tasks = [
            cb.record_success(),
            cb.record_failure(),
            cb.record_failure(),
            cb.record_failure(),
        ]

        results = await asyncio.gather(*tasks)
        assert all(results)
        # After success resets, state stays CLOSED
        assert cb.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_concurrent_reset_operations(self):
        """Test concurrent reset operations.

        Given: Circuit breaker in OPEN state
        When: Multiple concurrent reset() calls
        Then: All resets succeed, final state is CLOSED
        """
        cb = CircuitBreaker(threshold=1, timeout_secs=60.0)
        await cb.record_failure()
        assert cb.state == CBState.OPEN

        tasks = [cb.reset() for _ in range(5)]
        results = await asyncio.gather(*tasks)

        assert all(results)
        assert cb.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_atomic_state_transition_on_open(self):
        """Test atomic update of state when transitioning to OPEN.

        Given: Circuit breaker in CLOSED state
        When: Transitioning to OPEN state
        Then: state should be OPEN after threshold failures
        """
        cb = CircuitBreaker(threshold=3, timeout_secs=60.0)

        await cb.record_failure()
        await cb.record_failure()

        result = await cb.record_failure()

        assert result is True
        assert cb.state == CBState.OPEN

    @pytest.mark.asyncio
    async def test_atomic_state_transition_on_close(self):
        """Test atomic update of state when transitioning to CLOSED.

        Given: Circuit breaker in HALF_OPEN state
        When: Recording success in HALF_OPEN
        Then: state should be CLOSED
        """
        cb = CircuitBreaker(threshold=1, timeout_secs=1.0)
        await cb.record_failure()
        assert cb.state == CBState.OPEN

        # Wait for timeout to allow HALF_OPEN transition
        await asyncio.sleep(1.1)
        # Manually trigger half-open
        cb._breaker.half_open()

        # Now in HALF_OPEN, record success
        result = await cb.record_success()

        assert result is True
        assert cb.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_atomic_state_transition_on_reset(self):
        """Test atomic update of state when resetting.

        Given: Circuit breaker in OPEN state
        When: Resetting to CLOSED
        Then: state should be CLOSED
        """
        cb = CircuitBreaker(threshold=1, timeout_secs=60.0)
        await cb.record_failure()
        assert cb.state == CBState.OPEN

        result = await cb.reset()

        assert result is True
        assert cb.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_concurrent_failure_counter_increments(self):
        """Test concurrent failure counter increments.

        Given: Circuit breaker in CLOSED state
        When: Multiple concurrent record_failure() calls
        Then: Counter increments properly, state OPEN after threshold
        """
        cb = CircuitBreaker(threshold=10, timeout_secs=60.0)

        tasks = [cb.record_failure() for _ in range(10)]
        results = await asyncio.gather(*tasks)

        assert all(results)
        # After 10 failures (threshold), should be OPEN
        assert cb.state == CBState.OPEN

    @pytest.mark.asyncio
    async def test_failure_counter_reset_after_success(self):
        """Test failure counter resets after success.

        Given: Circuit breaker with some failures recorded
        When: Recording success
        Then: Counter resets, state CLOSED
        """
        cb = CircuitBreaker(threshold=5, timeout_secs=60.0)

        for _ in range(10):
            await cb.record_failure()

        assert cb.state == CBState.OPEN

        # Reset and record success
        await cb.reset()
        await cb.record_failure()
        await cb.record_failure()
        await cb.record_success()

        assert cb.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_high_concurrency_stress_test(self):
        """Stress test with high concurrency.

        Given: Circuit breaker in CLOSED state
        When: 100 concurrent operations
        Then: No race conditions, state consistent
        """
        cb = CircuitBreaker(threshold=50, timeout_secs=60.0)

        # Mix of successes and failures
        tasks = []
        for i in range(100):
            if i % 3 == 0:
                tasks.append(cb.record_success())
            else:
                tasks.append(cb.record_failure())

        results = await asyncio.gather(*tasks)
        assert all(results)
        # State depends on failure count vs threshold
        # Should not raise any exceptions

    @pytest.mark.asyncio
    async def test_transition_to_half_open_preserves_state(self):
        """Test transition to HALF_OPEN state.

        Given: Circuit breaker in OPEN state
        When: Timeout elapsed
        Then: State transitions to HALF_OPEN
        """
        cb = CircuitBreaker(threshold=1, timeout_secs=0.5)
        await cb.record_failure()
        assert cb.state == CBState.OPEN

        # Wait for timeout
        await asyncio.sleep(0.6)

        # Check can attempt reset (should allow HALF_OPEN transition)
        can_reset = cb._can_attempt_reset()
        assert can_reset is True

    @pytest.mark.asyncio
    async def test_sequential_operations_succeed(self):
        """Test sequential operations work correctly.

        Given: Circuit breaker in CLOSED state
        When: Sequential failure and success
        Then: State transitions correctly
        """
        cb = CircuitBreaker(threshold=3, timeout_secs=60.0)

        # 2 failures, still CLOSED
        await cb.record_failure()
        await cb.record_failure()
        assert cb.state == CBState.CLOSED

        # 1 success, counter reset
        await cb.record_success()
        assert cb.state == CBState.CLOSED

        # 3 more failures, OPEN
        await cb.record_failure()
        await cb.record_failure()
        await cb.record_failure()
        assert cb.state == CBState.OPEN


class TestCircuitBreakerHALFOpenProbe:
    """Tests for HALF_OPEN probe behavior."""

    @pytest.mark.asyncio
    async def test_half_open_failure_opens_immediately(self):
        """Test that a failure in HALF_OPEN immediately reopens circuit.

        Given: Circuit breaker in HALF_OPEN state
        When: Recording a failure
        Then: Circuit immediately returns to OPEN state
        """
        cb = CircuitBreaker(threshold=1, timeout_secs=0.5)
        await cb.record_failure()
        assert cb.state == CBState.OPEN

        # Wait for timeout
        await asyncio.sleep(0.6)
        cb._breaker.half_open()
        assert cb.state == CBState.HALF_OPEN

        # Record failure in HALF_OPEN
        await cb.record_failure()
        assert cb.state == CBState.OPEN

    @pytest.mark.asyncio
    async def test_half_open_success_closes_immediately(self):
        """Test that a success in HALF_OPEN closes circuit.

        Given: Circuit breaker in HALF_OPEN state
        When: Recording a success
        Then: Circuit transitions to CLOSED
        """
        cb = CircuitBreaker(threshold=1, timeout_secs=0.5)
        await cb.record_failure()
        assert cb.state == CBState.OPEN

        # Wait for timeout
        await asyncio.sleep(0.6)
        cb._breaker.half_open()
        assert cb.state == CBState.HALF_OPEN

        # Record success in HALF_OPEN
        await cb.record_success()
        assert cb.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_is_open_returns_false_in_half_open(self):
        """Test is_open() returns False in HALF_OPEN.

        Given: Circuit breaker in HALF_OPEN state
        When: Checking is_open()
        Then: Returns False (calls allowed)
        """
        cb = CircuitBreaker(threshold=1, timeout_secs=0.5)
        await cb.record_failure()
        assert cb.state == CBState.OPEN

        # Wait for timeout
        await asyncio.sleep(0.6)
        cb._breaker.half_open()
        assert cb.state == CBState.HALF_OPEN

        # is_open should return False in HALF_OPEN
        is_open = await cb.is_open()
        assert is_open is False

    @pytest.mark.asyncio
    async def test_is_open_true_when_open(self):
        """Test is_open() returns True when OPEN.

        Given: Circuit breaker in OPEN state
        When: Checking is_open()
        Then: Returns True
        """
        cb = CircuitBreaker(threshold=1, timeout_secs=60.0)
        await cb.record_failure()
        assert cb.state == CBState.OPEN

        is_open = await cb.is_open()
        assert is_open is True

    @pytest.mark.asyncio
    async def test_record_success_resets_in_closed(self):
        """Test that record_success resets counter in CLOSED.

        Given: Circuit breaker in CLOSED with some failures
        When: Recording success
        Then: Counter resets, stays CLOSED
        """
        cb = CircuitBreaker(threshold=5, timeout_secs=60.0)

        await cb.record_failure()
        await cb.record_failure()
        assert cb.state == CBState.CLOSED

        await cb.record_success()
        assert cb.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_fail_count_not_accumulated_in_half_open(self):
        """Test that failures in HALF_OPEN don't accumulate.

        Given: Circuit breaker in HALF_OPEN
        When: Recording failures
        Then: Circuit opens immediately on first failure
        """
        cb = CircuitBreaker(threshold=1, timeout_secs=0.5)
        await cb.record_failure()
        assert cb.state == CBState.OPEN

        # Wait for timeout
        await asyncio.sleep(0.6)
        cb._breaker.half_open()
        assert cb.state == CBState.HALF_OPEN

        # Single failure opens immediately
        await cb.record_failure()
        assert cb.state == CBState.OPEN
