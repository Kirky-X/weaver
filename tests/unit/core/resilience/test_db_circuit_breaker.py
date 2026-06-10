# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for DatabaseCircuitBreaker — DB-specific circuit breaker."""

from unittest.mock import patch

import pytest

from core.resilience.db_circuit_breaker import DatabaseCircuitBreaker


class TestDBCircuitBreakerFailMax:
    """DatabaseCircuitBreaker opens after 3 failures (fail_max=3)."""

    def test_db_circuit_breaker_fail_max_3(self):
        """3 failures opens the circuit."""
        cb = DatabaseCircuitBreaker()
        assert not cb.is_open

        cb.record_failure()
        assert not cb.is_open  # 1 failure

        cb.record_failure()
        assert not cb.is_open  # 2 failures

        cb.record_failure()
        assert cb.is_open  # 3 failures → OPEN

    def test_db_circuit_breaker_starts_closed(self):
        """Circuit breaker starts in closed state."""
        cb = DatabaseCircuitBreaker()
        assert not cb.is_open


class TestDBCircuitBreakerResetTimeout:
    """DatabaseCircuitBreaker transitions to half-open after 30s."""

    def test_db_circuit_breaker_reset_timeout_30s(self):
        """30s half-open transition."""
        cb = DatabaseCircuitBreaker()
        # Verify the internal breaker has reset_timeout=30.0
        assert cb._breaker.reset_timeout == 30.0

    def test_db_circuit_breaker_half_open_after_timeout(self):
        """After reset_timeout, circuit transitions to half-open."""
        cb = DatabaseCircuitBreaker()

        # Open the circuit
        for _ in range(3):
            cb.record_failure()
        assert cb.is_open

        # Simulate time passing beyond reset_timeout
        from datetime import UTC, datetime, timedelta

        # Patch the opened_at timestamp to be 31 seconds ago
        cb._breaker._state_storage.opened_at = datetime.now(UTC) - timedelta(seconds=31)

        # After timeout, is_open should return False (half-open state)
        assert not cb.is_open


class TestDBCircuitBreakerIndependence:
    """DB and LLM circuit breakers are independent."""

    def test_db_circuit_breaker_independent_from_llm(self):
        """DB and LLM breakers are independent — DB failure doesn't affect LLM."""
        from core.llm.resilience.circuit_breaker import ProviderCircuitBreaker

        db_cb = DatabaseCircuitBreaker(name="database")
        llm_cb = ProviderCircuitBreaker(name="llm", fail_max=5, reset_timeout=60.0)

        # Open DB breaker
        for _ in range(3):
            db_cb.record_failure()
        assert db_cb.is_open

        # LLM breaker should still be closed
        assert not llm_cb.is_open

        # Open LLM breaker
        for _ in range(5):
            llm_cb.record_failure()
        assert llm_cb.is_open

        # Reset DB breaker
        db_cb.record_success()
        # LLM should still be open
        assert llm_cb.is_open


class TestDBCircuitBreakerSuccess:
    """Success recording closes the circuit."""

    def test_success_resets_failure_count(self):
        """Recording success resets failure count."""
        cb = DatabaseCircuitBreaker()

        cb.record_failure()
        cb.record_failure()
        assert not cb.is_open  # 2 failures, not yet open

        cb.record_success()
        # After success, failure counter resets
        # Need 3 more failures to open
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_open  # Only 2 failures after reset

        cb.record_failure()
        assert cb.is_open  # 3rd failure opens it
