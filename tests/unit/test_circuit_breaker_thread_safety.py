# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for CircuitBreaker thread safety.

Tests for concurrent state transitions, atomic updates,
HALF_OPEN probe behavior, and async is_open() serialization.
"""

import asyncio
import time

import pytest

from core.resilience.circuit_breaker import CBState, CircuitBreaker


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
        assert cb.state == CBState.OPEN
        assert cb._fail_count == 15

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

        assert cb._fail_count == 3

        tasks = [
            cb.record_success(),
            cb.record_failure(),
            cb.record_failure(),
            cb.record_failure(),
        ]

        results = await asyncio.gather(*tasks)
        assert all(results)
        assert cb._fail_count in {0, 1, 2, 3}
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
        assert cb._fail_count == 0
        assert cb._opened_at == 0.0

    @pytest.mark.asyncio
    async def test_atomic_state_and_metadata_update_on_open(self):
        """Test atomic update of state and metadata when transitioning to OPEN.

        Given: Circuit breaker in CLOSED state
        When: Transitioning to OPEN state
        Then: _state and _opened_at should be updated atomically
        """
        cb = CircuitBreaker(threshold=3, timeout_secs=60.0)

        await cb.record_failure()
        await cb.record_failure()

        time_before = time.monotonic()
        result = await cb.record_failure()
        time_after = time.monotonic()

        assert result is True
        assert cb.state == CBState.OPEN
        assert cb._opened_at >= time_before
        assert cb._opened_at <= time_after
        assert cb._fail_count == 3

    @pytest.mark.asyncio
    async def test_atomic_state_and_metadata_update_on_close(self):
        """Test atomic update of state and metadata when transitioning to CLOSED.

        Given: Circuit breaker in OPEN state
        When: Recording success to transition to CLOSED
        Then: _state and _fail_count should be updated atomically
        """
        cb = CircuitBreaker(threshold=1, timeout_secs=60.0)
        await cb.record_failure()
        assert cb.state == CBState.OPEN
        assert cb._fail_count == 1
        assert cb._opened_at > 0

        result = await cb.record_success()
        assert result is True
        assert cb.state == CBState.CLOSED
        assert cb._fail_count == 0

    @pytest.mark.asyncio
    async def test_atomic_state_and_metadata_update_on_reset(self):
        """Test atomic update of state and metadata on manual reset.

        Given: Circuit breaker in OPEN state
        When: Calling reset()
        Then: All metadata should be reset atomically
        """
        cb = CircuitBreaker(threshold=1, timeout_secs=60.0)
        await cb.record_failure()
        assert cb.state == CBState.OPEN
        assert cb._fail_count == 1
        opened_at_value = cb._opened_at
        assert opened_at_value > 0

        result = await cb.reset()
        assert result is True
        assert cb.state == CBState.CLOSED
        assert cb._fail_count == 0
        assert cb._opened_at == 0.0

    @pytest.mark.asyncio
    async def test_concurrent_failure_counter_increments(self):
        """Test failure counter increments are not lost due to race conditions.

        Given: Circuit breaker in CLOSED state
        When: Multiple concurrent failures are recorded
        Then: All increments should be preserved (no lost updates)
        """
        cb = CircuitBreaker(threshold=100, timeout_secs=60.0)

        num_failures = 50
        tasks = [cb.record_failure() for _ in range(num_failures)]
        results = await asyncio.gather(*tasks)

        assert all(results)
        assert cb._fail_count == num_failures

    @pytest.mark.asyncio
    async def test_failure_counter_reset_during_concurrent_failures(self):
        """Test failure counter reset is atomic with state transition.

        Given: Circuit breaker recording failures
        When: reset() is called during concurrent failures
        Then: Reset should be atomic, subsequent failures counted correctly
        """
        cb = CircuitBreaker(threshold=100, timeout_secs=60.0)

        for _ in range(10):
            await cb.record_failure()
        assert cb._fail_count == 10

        tasks = [
            cb.reset(),
            cb.record_failure(),
            cb.record_failure(),
            cb.record_failure(),
        ]

        results = await asyncio.gather(*tasks)
        assert all(results)
        assert cb._fail_count >= 3
        assert cb.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_high_concurrency_stress_test(self):
        """Stress test with high concurrency.

        Given: Circuit breaker with high threshold
        When: Many concurrent operations of different types
        Then: System should remain consistent
        """
        cb = CircuitBreaker(threshold=100, timeout_secs=60.0)

        tasks = []
        for i in range(100):
            if i % 3 == 0:
                tasks.append(cb.record_failure())
            elif i % 3 == 1:
                tasks.append(cb.record_success())
            else:
                tasks.append(cb.reset())

        results = await asyncio.gather(*tasks)
        assert all(results)
        assert cb.state in {CBState.CLOSED, CBState.OPEN}
        assert cb._fail_count >= 0

    @pytest.mark.asyncio
    async def test_transition_to_half_open_preserves_metadata(self):
        """Test transition to HALF_OPEN preserves fail_count.

        Given: Circuit breaker in OPEN state
        When: Transitioning to HALF_OPEN (via is_open())
        Then: _state changes to HALF_OPEN and _fail_count resets to 0
        """
        cb = CircuitBreaker(threshold=1, timeout_secs=0.1)

        await cb.record_failure()
        assert cb.state == CBState.OPEN
        assert cb._fail_count == 1
        opened_at_value = cb._opened_at

        await asyncio.sleep(0.15)
        result = await cb.is_open()

        assert result is False
        assert cb.state == CBState.HALF_OPEN
        assert cb._fail_count == 0
        assert cb._opened_at == opened_at_value

    @pytest.mark.asyncio
    async def test_sequential_operations_succeed(self):
        """Test sequential operations without lock contention succeed.

        Given: Circuit breaker with no lock contention
        When: Performing sequential operations
        Then: All should succeed
        """
        cb = CircuitBreaker(threshold=5, timeout_secs=60.0)

        assert await cb.record_failure() is True
        assert await cb.record_failure() is True
        assert cb._fail_count == 2

        assert await cb.record_success() is True
        assert cb._fail_count == 0

        for _ in range(5):
            assert await cb.record_failure() is True
        assert cb.state == CBState.OPEN

        assert await cb.reset() is True
        assert cb.state == CBState.CLOSED


class TestCircuitBreakerHALFOpenProbe:
    """Tests for HALF_OPEN probe behavior after fix."""

    @pytest.mark.asyncio
    async def test_half_open_failure_opens_immediately(self):
        """Test HALF_OPEN probe failure immediately reopens circuit.

        Given: Circuit breaker in HALF_OPEN state
        When: A probe request fails (record_failure called)
        Then: Circuit immediately transitions to OPEN
        And: Does not wait for fail_count to reach threshold
        """
        cb = CircuitBreaker(threshold=1, timeout_secs=0.1)

        await cb.record_failure()
        assert cb.state == CBState.OPEN
        await asyncio.sleep(0.15)

        await cb.is_open()
        assert cb.state == CBState.HALF_OPEN
        assert cb._fail_count == 0

        await cb.record_failure()
        assert cb.state == CBState.OPEN
        assert cb._opened_at > 0

    @pytest.mark.asyncio
    async def test_half_open_success_closes_immediately(self):
        """Test HALF_OPEN probe success immediately closes circuit.

        Given: Circuit breaker in HALF_OPEN state
        When: A probe request succeeds (record_success called)
        Then: Circuit immediately transitions to CLOSED
        And: _opened_at is reset to 0.0
        """
        cb = CircuitBreaker(threshold=1, timeout_secs=0.1)

        await cb.record_failure()
        assert cb.state == CBState.OPEN
        await asyncio.sleep(0.15)

        await cb.is_open()
        assert cb.state == CBState.HALF_OPEN
        assert cb._fail_count == 0
        opened_at_before = cb._opened_at
        assert opened_at_before > 0

        await cb.record_success()
        assert cb.state == CBState.CLOSED
        assert cb._fail_count == 0
        assert cb._opened_at == 0.0

    @pytest.mark.asyncio
    async def test_is_open_serializes_half_open_transition(self):
        """Test only one caller triggers OPEN→HALF_OPEN transition.

        Given: Circuit breaker in OPEN state with timeout elapsed
        When: Multiple coroutines concurrently call is_open()
        Then: Exactly one of them performs the HALF_OPEN transition
        And: All others detect HALF_OPEN and return False
        And: _fail_count is reset exactly once
        """
        cb = CircuitBreaker(threshold=1, timeout_secs=0.1)

        await cb.record_failure()
        await asyncio.sleep(0.15)
        assert cb.state == CBState.OPEN

        tasks = [cb.is_open() for _ in range(10)]
        results = await asyncio.gather(*tasks)

        assert all(r is False for r in results)
        assert cb.state == CBState.HALF_OPEN
        assert cb._fail_count == 0

    @pytest.mark.asyncio
    async def test_is_open_false_when_closed(self):
        """Test is_open returns False when circuit is closed."""
        cb = CircuitBreaker()
        assert await cb.is_open() is False

    @pytest.mark.asyncio
    async def test_is_open_true_when_open(self):
        """Test is_open returns True when circuit is open and not timed out."""
        cb = CircuitBreaker(threshold=2, timeout_secs=60.0)
        await cb.record_failure()
        await cb.record_failure()
        assert await cb.is_open() is True

    @pytest.mark.asyncio
    async def test_record_success_resets_fail_count_in_closed(self):
        """Test record_success resets fail_count in CLOSED state."""
        cb = CircuitBreaker(threshold=5)
        await cb.record_failure()
        await cb.record_failure()
        await cb.record_failure()
        assert cb._fail_count == 3
        await cb.record_success()
        assert cb._fail_count == 0
        assert cb.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_fail_count_not_accumulated_in_half_open(self):
        """Test fail_count does NOT accumulate in HALF_OPEN state.

        After the fix, record_failure in HALF_OPEN immediately opens
        the circuit without incrementing fail_count.
        """
        cb = CircuitBreaker(threshold=1, timeout_secs=0.1)

        await cb.record_failure()
        await asyncio.sleep(0.15)
        await cb.is_open()
        assert cb.state == CBState.HALF_OPEN
        assert cb._fail_count == 0

        await cb.record_failure()
        assert cb.state == CBState.OPEN
        assert cb._fail_count == 0
