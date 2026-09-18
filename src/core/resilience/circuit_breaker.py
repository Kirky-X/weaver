# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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
import time

from pybreaker import CircuitBreaker as PyBreaker

from core.constants import CircuitState as CBState
from core.observability import get_logger
from core.observability.metrics import metrics

log = get_logger(__name__)


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
        # Self-maintained counters and timestamps to avoid pybreaker's
        # private _state_storage API. These mirror what pybreaker would
        # track internally but expose via private attributes.
        self._failure_counter: int = 0
        self._success_counter: int = 0
        # Monotonic timestamp (time.monotonic) — wall-clock jumps from NTP
        # sync must not skew the OPEN→HALF_OPEN cooldown. Mirrors
        # ProviderCircuitBreaker in core.llm.resilience.
        self._opened_at: float | None = None
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

        The OPEN→HALF_OPEN transition does NOT happen here: pybreaker's
        ``current_state`` property is a pure read (it never advances the state
        machine). Only ``CircuitBreaker.call()`` does, via
        ``CircuitOpenState.before_call``. Because this wrapper stores its own
        ``_opened_at`` timestamp, the cooldown check below is what actually
        decides whether calls may proceed.

        Returns:
            True if calls should be blocked (OPEN, not yet timed out).
            False if calls may proceed (CLOSED or HALF_OPEN).
        """
        current_state = self.state
        return current_state == CBState.OPEN and not self._can_attempt_reset()

    def _can_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset from OPEN state."""
        if self._opened_at is None:
            return False
        return (time.monotonic() - self._opened_at) >= self._timeout

    async def record_success(self) -> bool:
        """Record a successful operation.

        In HALF_OPEN: closes the circuit immediately.
        In CLOSED: resets failure counter.
        """
        async with self._lock:
            prev_state = self.state

            if prev_state == CBState.HALF_OPEN:
                self._success_counter += 1
                if self._success_counter >= self._breaker.success_threshold:
                    self._success_counter = 0
                    self._failure_counter = 0
                    self._opened_at = None
                    self._breaker.close()
                    self._emit_state_transition(CBState.HALF_OPEN, CBState.CLOSED)
            else:
                # In CLOSED state, reset counters on success
                self._success_counter = 0
                self._failure_counter = 0
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

            if prev_state == CBState.HALF_OPEN:
                self._failure_counter = 0
                self._success_counter = 0
                self._opened_at = time.monotonic()
                self._breaker.open()
                self._emit_state_transition(CBState.HALF_OPEN, CBState.OPEN)
            else:
                self._failure_counter += 1
                if self._failure_counter >= self._breaker.fail_max:
                    self._failure_counter = 0
                    self._success_counter = 0
                    self._opened_at = time.monotonic()
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
            self._failure_counter = 0
            self._success_counter = 0
            self._opened_at = None
            self._breaker.close()
            if prev_state != CBState.CLOSED:
                self._emit_state_transition(prev_state, CBState.CLOSED)
            metrics.circuit_breaker_state.labels(provider=self._provider).set(
                self.STATE_CODES[CBState.CLOSED]
            )
            return True

    def force_half_open(self) -> None:  # pragma: no cover
        """Force the circuit breaker into HALF_OPEN state.

        Test-only helper that delegates to the underlying pybreaker
        instance's half_open() method. Deliberately bypasses ``self._lock``
        (sync helper, no concurrent production callers) and only transitions
        from OPEN — calling it on a CLOSED circuit would corrupt the state
        machine.
        """
        if self.state is CBState.OPEN:
            self._breaker.half_open()
        else:
            log.warning(
                "force_half_open_ignored",
                provider=self._provider,
                state=self.state.value,
            )

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
