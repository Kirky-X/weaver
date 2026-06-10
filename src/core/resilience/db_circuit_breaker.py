# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Database-specific circuit breaker with fail_max=3, reset_timeout=30s.

Unlike the LLM circuit breaker (fail_max=5, reset_timeout=60s),
the DB circuit breaker uses tighter thresholds because database
failures typically indicate infrastructure issues that need faster
detection and quicker recovery attempts.
"""

from __future__ import annotations

from pybreaker import CircuitBreaker as PyBreaker

from core.observability.logging import get_logger

log = get_logger(__name__)


class DatabaseCircuitBreaker:
    """Circuit breaker for database connections.

    Config: fail_max=3, reset_timeout=30.0
    Uses pybreaker.CircuitBreaker internally.

    Implements: CircuitBreaker (for dependency injection)
    """

    def __init__(self, name: str = "database") -> None:
        """Initialize the database circuit breaker.

        Args:
            name: Name for logging and identification.
        """
        self._breaker = PyBreaker(
            name=name,
            fail_max=3,
            reset_timeout=30.0,
        )

    @property
    def is_open(self) -> bool:
        """Check if the circuit is open (calls should be blocked).

        Returns:
            True if the circuit is open, False if closed or half-open.
        """
        state = self._breaker.current_state
        if state == "open":
            # Check if enough time has passed for half-open transition
            from datetime import UTC, datetime

            opened_at = self._breaker._state_storage.opened_at
            if opened_at is None:
                return True
            if isinstance(opened_at, datetime):
                elapsed = (datetime.now(UTC) - opened_at).total_seconds()
            else:
                import time

                elapsed = time.monotonic() - opened_at
            return elapsed < self._breaker.reset_timeout
        return False

    def record_success(self) -> None:
        """Record a successful database operation.

        In half-open state: closes the circuit.
        In closed state: resets failure counter.
        """
        storage = self._breaker._state_storage
        if self._breaker.current_state == "half-open":
            storage.increment_success_counter()
            if self._breaker.success_counter >= self._breaker.success_threshold:
                self._breaker.close()
                log.info("db_circuit_closed_after_success", name=self._breaker.name)
        else:
            storage.reset_counter()
            self._breaker.close()

    def record_failure(self) -> None:
        """Record a failed database operation.

        In half-open state: immediately re-opens the circuit.
        In closed state: increments counter; opens if fail_max reached.
        """
        storage = self._breaker._state_storage
        if self._breaker.current_state == "half-open":
            self._breaker.open()
            log.warning("db_circuit_reopened_after_half_open_failure", name=self._breaker.name)
        else:
            storage.increment_counter()
            if self._breaker.fail_counter >= self._breaker.fail_max:
                self._breaker.open()
                log.error(
                    "db_circuit_opened_after_failures",
                    name=self._breaker.name,
                    fail_counter=self._breaker.fail_counter,
                    fail_max=self._breaker.fail_max,
                )

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        self._breaker._state_storage.reset_counter()
        self._breaker.close()
        log.info("db_circuit_manually_reset", name=self._breaker.name)
