# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Generic circuit breaker for fault tolerance.

State machine:
  CLOSED  → (consecutive failures >= threshold) → OPEN
  OPEN    → (cooldown period elapsed)           → HALF_OPEN
  HALF_OPEN → (probe success)                   → CLOSED
  HALF_OPEN → (probe failure)                   → OPEN
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum

from core.observability.logging import get_logger

log = get_logger("circuit_breaker")


class CBState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """In-process circuit breaker with async-safe state transitions.

    All state-changing operations use asyncio.Lock for atomicity.
    The OPEN→HALF_OPEN transition happens atomically inside is_open().

    Args:
        threshold: Number of consecutive failures before opening.
        timeout_secs: Cooldown period in seconds before transitioning
            from OPEN to HALF_OPEN.
    """

    def __init__(self, threshold: int = 5, timeout_secs: float = 60.0) -> None:
        self._threshold = threshold
        self._timeout = timeout_secs
        self._state = CBState.CLOSED
        self._fail_count = 0
        self._opened_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CBState:
        """Current circuit breaker state (read-only, no lock)."""
        return self._state

    async def is_open(self) -> bool:
        """Check if the circuit is open and atomically transition OPEN→HALF_OPEN.

        Returns:
            True if calls should be blocked (OPEN, not yet timed out).
            False if calls may proceed (CLOSED or HALF_OPEN).
        """
        async with self._lock:
            if self._state == CBState.OPEN:
                if time.monotonic() - self._opened_at >= self._timeout:
                    self._state = CBState.HALF_OPEN
                    self._fail_count = 0
                    log.info("circuit_breaker_half_open")
                    return False
                return True
            return False

    async def record_success(self) -> bool:
        """Record a successful operation.

        In HALF_OPEN: closes the circuit immediately.
        In CLOSED: resets failure counter.
        """
        async with self._lock:
            if self._state == CBState.HALF_OPEN:
                self._state = CBState.CLOSED
                self._fail_count = 0
                self._opened_at = 0.0
                log.info("circuit_breaker_closed_from_half_open")
                return True
            self._fail_count = 0
            self._state = CBState.CLOSED
            return True

    async def record_failure(self) -> bool:
        """Record a failed operation.

        In HALF_OPEN: immediately re-opens the circuit (probe failed).
        In CLOSED: increments counter; opens if threshold reached.
        """
        async with self._lock:
            if self._state == CBState.HALF_OPEN:
                self._state = CBState.OPEN
                self._opened_at = time.monotonic()
                self._fail_count = 0
                log.warning("circuit_breaker_reopened_from_half_open")
                return True
            self._fail_count += 1
            if self._fail_count >= self._threshold:
                self._state = CBState.OPEN
                self._opened_at = time.monotonic()
            return True

    async def reset(self) -> bool:
        """Manually reset the circuit breaker to CLOSED state."""
        async with self._lock:
            self._fail_count = 0
            self._state = CBState.CLOSED
            self._opened_at = 0.0
            return True
