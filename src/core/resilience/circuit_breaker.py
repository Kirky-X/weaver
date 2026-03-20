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
    """Simple in-process circuit breaker.

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
        """Current circuit breaker state."""
        return self._state

    def is_open(self) -> bool:
        """Check if the circuit is open (calls should be blocked).

        Also handles the OPEN → HALF_OPEN transition when the
        cooldown period has elapsed.

        Returns:
            True if calls should be blocked.
        """
        if self._state == CBState.OPEN:
            if time.monotonic() - self._opened_at >= self._timeout:
                self._state = CBState.HALF_OPEN
                return False
            return True
        return False

    async def _transition_to(self, new_state: CBState) -> bool:
        """Transition to a new state with thread-safe lock protection.

        Uses a 5-second timeout for lock acquisition. If timeout occurs,
        logs a warning and skips the transition.

        Args:
            new_state: The target state to transition to.

        Returns:
            True if transition succeeded, False if timeout occurred.
        """
        try:
            async with asyncio.timeout(5.0):
                async with self._lock:
                    self._state = new_state
                    if new_state == CBState.OPEN:
                        self._opened_at = time.monotonic()
                    return True
        except TimeoutError:
            log.warning(
                "circuit_breaker_lock_timeout",
                current_state=self._state.value,
                target_state=new_state.value,
            )
            return False

    async def record_success(self) -> bool:
        """Record a successful operation. Resets the breaker to CLOSED.

        Thread-safe with 5-second lock timeout.

        Returns:
            True if the operation succeeded, False if timeout occurred.
        """
        try:
            async with asyncio.timeout(5.0):
                async with self._lock:
                    self._fail_count = 0
                    self._state = CBState.CLOSED
                    return True
        except TimeoutError:
            log.warning("circuit_breaker_record_success_timeout")
            return False

    async def record_failure(self) -> bool:
        """Record a failed operation. Opens the breaker if threshold reached.

        Thread-safe with 5-second lock timeout.

        Returns:
            True if the operation succeeded, False if timeout occurred.
        """
        try:
            async with asyncio.timeout(5.0):
                async with self._lock:
                    self._fail_count += 1
                    if self._fail_count >= self._threshold:
                        self._state = CBState.OPEN
                        self._opened_at = time.monotonic()
                    return True
        except TimeoutError:
            log.warning("circuit_breaker_record_failure_timeout")
            return False

    async def reset(self) -> bool:
        """Manually reset the circuit breaker to CLOSED state.

        Thread-safe with 5-second lock timeout.

        Returns:
            True if the operation succeeded, False if timeout occurred.
        """
        try:
            async with asyncio.timeout(5.0):
                async with self._lock:
                    self._fail_count = 0
                    self._state = CBState.CLOSED
                    self._opened_at = 0.0
                    return True
        except TimeoutError:
            log.warning("circuit_breaker_reset_timeout")
            return False
