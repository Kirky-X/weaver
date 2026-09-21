# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Regression tests for core/resilience HIGH findings (OCR report).

Covers: (force_half_open state guard), (per-call retryer).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from core.resilience.circuit_breaker import CBState, CircuitBreaker
from core.resilience.retry import _create_retry_decorator


class TestForceHalfOpenGuard:
    """force_half_open must not corrupt a CLOSED circuit."""

    def test_ignored_when_closed(self) -> None:
        breaker = CircuitBreaker(threshold=3, timeout_secs=60, provider="p")
        assert breaker.state is CBState.CLOSED

        breaker.force_half_open()

        assert breaker.state is CBState.CLOSED

    async def test_applies_when_open(self) -> None:
        breaker = CircuitBreaker(threshold=1, timeout_secs=60, provider="p")
        await breaker.record_failure()
        assert breaker.state is CBState.OPEN

        breaker.force_half_open()

        assert breaker.state is CBState.HALF_OPEN


class TestPerCallRetryer:
    """A fresh retryer instance must be created per call."""

    async def test_new_retryer_per_invocation(self) -> None:
        stub_instances: list[MagicMock] = []

        def factory_stub(**kwargs: Any) -> MagicMock:
            instance = MagicMock()
            stub_instances.append(instance)

            async def agen() -> Any:
                raise RuntimeError("exhausted")
                yield  # pragma: no cover

            instance.__aiter__ = lambda _self: agen()
            return instance

        async def fn() -> str:
            return "ok"

        wrapped = _create_retry_decorator(factory_stub, max_attempts=1)(fn)

        with pytest.raises(RuntimeError, match="exhausted"):
            await wrapped()
        with pytest.raises(RuntimeError, match="exhausted"):
            await wrapped()

        # Two concurrent-style invocations → two independent retryer instances
        assert len(stub_instances) == 2
