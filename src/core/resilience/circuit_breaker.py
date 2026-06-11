# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified circuit breaker using pybreaker with event emission.

This module provides a pybreaker-based circuit breaker implementation
that maintains the same interface as the previous generic implementation,
while adding event emission for state transitions.

State machine:
  CLOSED  → (consecutive failures >= threshold) → OPEN
  OPEN    → (cooldown period elapsed)           → HALF_OPEN
  HALF_OPEN → (probe success)                   → CLOSED
  HALF_OPEN → (probe failure)                   → OPEN
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import TYPE_CHECKING

from pybreaker import CircuitBreaker as PyBreaker

from core.observability import get_logger
from core.observability.metrics import metrics

if TYPE_CHECKING:
    pass

log = get_logger(__name__)


class CBState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Pybreaker-based circuit breaker with async support and event emission.

    Maintains the same interface as the previous generic implementation:
    - threshold: Number of consecutive failures before opening
    - timeout_secs: Cooldown period in seconds
    - provider: Name for metrics and events

    All state transitions emit CircuitStateEvent via the event bus.
    """

    # State code mapping for Prometheus metrics
    STATE_CODES = {
        CBState.CLOSED: 0,
        CBState.OPEN: 1,
        CBState.HALF_OPEN: 2,
    }

    # Map pybreaker state strings to CBState
    PYBREAKER_STATE_MAP = {
        "closed": CBState.CLOSED,
        "open": CBState.OPEN,
        "half-open": CBState.HALF_OPEN,
    }

    def __init__(
        self, threshold: int = 5, timeout_secs: float = 60.0, provider: str = "default"
    ) -> None:
        """Initialize circuit breaker with pybreaker backend.

        Args:
            threshold: Number of consecutive failures before opening.
            timeout_secs: Cooldown period in seconds before transitioning
                from OPEN to HALF_OPEN.
            provider: Provider name for Prometheus metrics labels and events.
        """
        self._threshold = threshold
        self._timeout = timeout_secs
        self._provider = provider
        self._breaker = PyBreaker(
            name=provider,
            fail_max=threshold,
            reset_timeout=timeout_secs,
        )
        self._lock = asyncio.Lock()
        self._last_state: CBState = CBState.CLOSED
        # Initialize metrics
        metrics.circuit_breaker_state.labels(provider=self._provider).set(
            self.STATE_CODES[CBState.CLOSED]
        )

    @property
    def state(self) -> CBState:
        """Current circuit breaker state."""
        py_state = self._breaker.current_state
        return self.PYBREAKER_STATE_MAP.get(py_state, CBState.CLOSED)

    async def is_open(self) -> bool:
        """Check if the circuit is open.

        pybreaker handles the OPEN→HALF_OPEN transition internally.
        This method just checks the current state.

        Returns:
            True if calls should be blocked (OPEN, not yet timed out).
            False if calls may proceed (CLOSED or HALF_OPEN).
        """
        current_state = self.state
        # pybreaker automatically transitions OPEN→HALF_OPEN after reset_timeout
        # when checking current_state or making a call
        return current_state == CBState.OPEN and not self._can_attempt_reset()

    def _can_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset from OPEN state."""
        from datetime import UTC, datetime

        opened_at = self._breaker._state_storage.opened_at
        if opened_at is None:
            return False
        if isinstance(opened_at, datetime):
            elapsed = (datetime.now(UTC) - opened_at).total_seconds()
        else:
            elapsed = time.monotonic() - opened_at
        return elapsed >= self._timeout

    async def record_success(self) -> bool:
        """Record a successful operation.

        In HALF_OPEN: closes the circuit immediately.
        In CLOSED: resets failure counter.
        """
        async with self._lock:
            prev_state = self.state
            storage = self._breaker._state_storage

            if prev_state == CBState.HALF_OPEN:
                storage.increment_success_counter()
                if self._breaker.success_counter >= self._breaker.success_threshold:
                    self._breaker.close()
                    self._emit_state_transition(CBState.HALF_OPEN, CBState.CLOSED)
            else:
                storage.reset_counter()
                self._breaker.close()

            metrics.circuit_breaker_state.labels(provider=self._provider).set(
                self.STATE_CODES[self.state]
            )
            return True

    async def record_failure(self) -> bool:
        """Record a failed operation.

        In HALF_OPEN: immediately re-opens the circuit (probe failed).
        In CLOSED: increments counter; opens if threshold reached.
        """
        async with self._lock:
            prev_state = self.state
            storage = self._breaker._state_storage

            if prev_state == CBState.HALF_OPEN:
                self._breaker.open()
                self._emit_state_transition(CBState.HALF_OPEN, CBState.OPEN)
            else:
                storage.increment_counter()
                if self._breaker.fail_counter >= self._breaker.fail_max:
                    self._breaker.open()
                    self._emit_state_transition(CBState.CLOSED, CBState.OPEN)

            metrics.circuit_breaker_state.labels(provider=self._provider).set(
                self.STATE_CODES[self.state]
            )
            metrics.circuit_breaker_failures.labels(provider=self._provider).inc()
            return True

    async def reset(self) -> bool:
        """Manually reset the circuit breaker to CLOSED state."""
        async with self._lock:
            prev_state = self.state
            self._breaker._state_storage.reset_counter()
            self._breaker.close()
            if prev_state != CBState.CLOSED:
                self._emit_state_transition(prev_state, CBState.CLOSED)
            metrics.circuit_breaker_state.labels(provider=self._provider).set(
                self.STATE_CODES[CBState.CLOSED]
            )
            return True

    def _emit_state_transition(self, from_state: CBState, to_state: CBState) -> None:
        """Emit a CircuitStateEvent for state transition.

        Args:
            from_state: Previous state.
            to_state: New state.
        """
        if from_state == to_state:
            return

        # Import here to avoid circular dependency
        from core.event import CircuitStateEvent, event_bus

        event = CircuitStateEvent(
            provider=self._provider,
            from_state=from_state.value,
            to_state=to_state.value,
            threshold=self._threshold,
            timeout_secs=self._timeout,
        )
        event_bus.emit(event)
        log.info(
            "circuit_state_transition",
            provider=self._provider,
            from_state=from_state.value,
            to_state=to_state.value,
        )
        self._last_state = to_state
