# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for circuit breaker OPEN→HALF_OPEN automatic recovery.

pybreaker transitions OPEN→HALF_OPEN only inside ``CircuitOpenState.before_call``
when ``self._breaker.call()`` is invoked. ProviderCircuitBreaker bypasses
``self._breaker.call()`` and calls ``func`` directly, so the state machine
transition must be replicated in the wrapper. These tests verify the wrapper
correctly transitions to HALF_OPEN after ``reset_timeout`` elapses and
returns to CLOSED on probe success or back to OPEN on probe failure.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from core.llm.resilience.circuit_breaker import (
    CircuitOpenError,
    ProviderCircuitBreaker,
)
from core.llm.types import CircuitState


def _force_open(cb: ProviderCircuitBreaker) -> None:
    """Drive the breaker into OPEN state via recorded failures."""
    for _ in range(cb._breaker.fail_max):
        cb.record_failure()
    assert cb.is_open, "breaker should be OPEN after fail_max failures"


class TestCircuitBreakerRecovery:
    """Verify OPEN→HALF_OPEN→CLOSED/OPEN recovery after reset_timeout."""

    def test_is_open_true_before_reset_timeout(self):
        cb = ProviderCircuitBreaker(name="test", fail_max=2, reset_timeout=60.0)
        _force_open(cb)
        assert cb.is_open is True
        assert cb.state == CircuitState.OPEN

    def test_is_open_false_after_reset_timeout(self):
        cb = ProviderCircuitBreaker(name="test", fail_max=2, reset_timeout=60.0)
        _force_open(cb)

        base = time.monotonic()
        with patch("core.llm.resilience.circuit_breaker.time.monotonic") as mock_now:
            mock_now.side_effect = lambda: base + 0.0  # opened_at moment
            # Re-mark opened_at with mocked clock
            cb._opened_at = mock_now()

            mock_now.side_effect = lambda: base + 61.0  # past reset_timeout
            assert cb.is_open is False
            assert cb.state == CircuitState.OPEN  # storage state unchanged by read

    @pytest.mark.asyncio
    async def test_call_raises_before_reset_timeout(self):
        cb = ProviderCircuitBreaker(name="test", fail_max=1, reset_timeout=60.0)
        _force_open(cb)

        async def success_func():
            return "ok"

        with pytest.raises(CircuitOpenError):
            await cb.call(success_func)

    @pytest.mark.asyncio
    async def test_call_transitions_to_half_open_after_timeout(self):
        cb = ProviderCircuitBreaker(name="test", fail_max=1, reset_timeout=60.0)
        _force_open(cb)

        base = time.monotonic()
        with patch("core.llm.resilience.circuit_breaker.time.monotonic") as mock_now:
            mock_now.side_effect = lambda: base
            cb._opened_at = mock_now()

            async def success_func():
                return "recovered"

            mock_now.side_effect = lambda: base + 61.0
            result = await cb.call(success_func)
            assert result == "recovered"
            assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_call_half_open_failure_reopens_circuit(self):
        cb = ProviderCircuitBreaker(name="test", fail_max=1, reset_timeout=60.0)
        _force_open(cb)

        base = time.monotonic()
        with patch("core.llm.resilience.circuit_breaker.time.monotonic") as mock_now:
            mock_now.side_effect = lambda: base
            cb._opened_at = mock_now()

            async def fail_func():
                raise RuntimeError("probe failed")

            mock_now.side_effect = lambda: base + 61.0
            with pytest.raises(RuntimeError):
                await cb.call(fail_func)

            assert cb.state == CircuitState.OPEN
            assert cb.is_open is True

    @pytest.mark.asyncio
    async def test_call_succeeds_repeatedly_after_recovery(self):
        cb = ProviderCircuitBreaker(name="test", fail_max=1, reset_timeout=60.0)
        _force_open(cb)

        base = time.monotonic()
        with patch("core.llm.resilience.circuit_breaker.time.monotonic") as mock_now:
            mock_now.side_effect = lambda: base
            cb._opened_at = mock_now()

            async def success_func():
                return "ok"

            mock_now.side_effect = lambda: base + 61.0
            await cb.call(success_func)
            mock_now.side_effect = lambda: base + 62.0
            result = await cb.call(success_func)
            assert result == "ok"
            assert cb.state == CircuitState.CLOSED

    def test_reset_clears_opened_at(self):
        cb = ProviderCircuitBreaker(name="test", fail_max=1, reset_timeout=60.0)
        _force_open(cb)
        assert cb._opened_at is not None
        cb.reset()
        assert cb._opened_at is None
        assert cb.state == CircuitState.CLOSED
