"""Generic circuit breaker for fault tolerance.

State machine:
  CLOSED  → (consecutive failures >= threshold) → OPEN
  OPEN    → (cooldown period elapsed)           → HALF_OPEN
  HALF_OPEN → (probe success)                   → CLOSED
  HALF_OPEN → (probe failure)                   → OPEN
"""

from __future__ import annotations

import time
from enum import Enum


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

    @property
    def state(self) -> CBState:
        """Current circuit breaker state."""
        # Check for timeout-triggered transition
        if self._state == CBState.OPEN:
            if time.monotonic() - self._opened_at >= self._timeout:
                self._state = CBState.HALF_OPEN
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

    def record_success(self) -> None:
        """Record a successful operation. Resets the breaker to CLOSED."""
        self._fail_count = 0
        self._state = CBState.CLOSED

    def record_failure(self) -> None:
        """Record a failed operation. Opens the breaker if threshold reached."""
        self._fail_count += 1
        if self._fail_count >= self._threshold:
            self._state = CBState.OPEN
            self._opened_at = time.monotonic()

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED state."""
        self._fail_count = 0
        self._state = CBState.CLOSED
        self._opened_at = 0.0
