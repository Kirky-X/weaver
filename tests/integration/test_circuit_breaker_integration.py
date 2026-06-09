# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for circuit breaker implementations.

Verifies that ProviderCircuitBreaker (core/llm/resilience/) and
CircuitBreaker (core/resilience/) handle state transitions consistently.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from core.llm.resilience.circuit_breaker import ProviderCircuitBreaker
from core.llm.types import CircuitState as OldCircuitState
from core.resilience.circuit_breaker import CBState, CircuitBreaker


class TestStateTransitionsConsistency:
    """Verify both implementations reach equivalent states for the same sequence."""

    @pytest.mark.asyncio
    async def test_initial_state_closed(self):
        new_cb = CircuitBreaker(threshold=3, timeout_secs=60.0)
        old_cb = ProviderCircuitBreaker(name="test", fail_max=3, reset_timeout=60.0)

        assert new_cb.state == CBState.CLOSED
        assert old_cb.state == OldCircuitState.CLOSED
        assert not old_cb.is_open

    @pytest.mark.asyncio
    async def test_state_after_failures(self):
        new_cb = CircuitBreaker(threshold=2, timeout_secs=60.0)
        old_cb = ProviderCircuitBreaker(name="test", fail_max=2, reset_timeout=60.0)

        for _ in range(2):
            await new_cb.record_failure()
            old_cb.record_failure()

        assert new_cb.state == CBState.OPEN
        assert old_cb.state == OldCircuitState.OPEN
        assert old_cb.is_open

    @pytest.mark.asyncio
    async def test_state_after_success_after_open(self):
        new_cb = CircuitBreaker(threshold=1, timeout_secs=0.1)
        old_cb = ProviderCircuitBreaker(name="test", fail_max=1, reset_timeout=0.1)

        await new_cb.record_failure()
        old_cb.record_failure()

        assert new_cb.state == CBState.OPEN
        assert old_cb.state == OldCircuitState.OPEN

        await asyncio.sleep(0.15)

        await new_cb.record_success()
        old_cb.record_success()

        assert new_cb.state == CBState.CLOSED
        assert old_cb.state == OldCircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failure_in_half_open_reopens(self):
        new_cb = CircuitBreaker(threshold=1, timeout_secs=0.1)
        old_cb = ProviderCircuitBreaker(name="test", fail_max=1, reset_timeout=0.1)

        await new_cb.record_failure()
        old_cb.record_failure()

        await asyncio.sleep(0.15)

        await new_cb.record_failure()
        old_cb.record_failure()

        assert new_cb.state == CBState.OPEN
        assert old_cb.state == OldCircuitState.OPEN

    @pytest.mark.asyncio
    async def test_reset_closes_circuit(self):
        new_cb = CircuitBreaker(threshold=2, timeout_secs=60.0)
        old_cb = ProviderCircuitBreaker(name="test", fail_max=2, reset_timeout=60.0)

        await new_cb.record_failure()
        old_cb.record_failure()
        await new_cb.record_failure()
        old_cb.record_failure()

        assert new_cb.state == CBState.OPEN
        assert old_cb.state == OldCircuitState.OPEN

        await new_cb.reset()
        old_cb.reset()

        assert new_cb.state == CBState.CLOSED
        assert old_cb.state == OldCircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_success_in_closed_resets_counter(self):
        new_cb = CircuitBreaker(threshold=3, timeout_secs=60.0)
        old_cb = ProviderCircuitBreaker(name="test", fail_max=3, reset_timeout=60.0)

        await new_cb.record_failure()
        old_cb.record_failure()
        await new_cb.record_failure()
        old_cb.record_failure()

        await new_cb.record_success()
        old_cb.record_success()

        assert new_cb.state == CBState.CLOSED
        assert old_cb.state == OldCircuitState.CLOSED

        await new_cb.record_failure()
        old_cb.record_failure()

        assert new_cb.state == CBState.CLOSED
        assert old_cb.state == OldCircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_single_failure_does_not_open(self):
        new_cb = CircuitBreaker(threshold=2, timeout_secs=60.0)
        old_cb = ProviderCircuitBreaker(name="test", fail_max=2, reset_timeout=60.0)

        await new_cb.record_failure()
        old_cb.record_failure()

        assert new_cb.state == CBState.CLOSED
        assert old_cb.state == OldCircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_concurrent_failure_sequences(self):
        new_cb = CircuitBreaker(threshold=3, timeout_secs=60.0)
        old_cb = ProviderCircuitBreaker(name="test", fail_max=3, reset_timeout=60.0)

        async def record_new():
            for _ in range(3):
                await new_cb.record_failure()

        def record_old():
            return [old_cb.record_failure() for _ in range(3)]

        await asyncio.gather(record_new())
        record_old()

        assert new_cb.state == CBState.OPEN
        assert old_cb.state == OldCircuitState.OPEN
