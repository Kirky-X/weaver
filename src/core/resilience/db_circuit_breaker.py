# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Database-specific circuit breaker factory.

Creates a CircuitBreaker with DB-optimized defaults:
- fail_max=3 (tighter than LLM's 5)
- reset_timeout=30s (faster recovery than LLM's 60s)

Database failures typically indicate infrastructure issues that need
faster detection and quicker recovery attempts.
"""

from __future__ import annotations

from core.resilience.circuit_breaker import CircuitBreaker


def create_db_circuit_breaker(name: str = "database") -> CircuitBreaker:
    """Create a circuit breaker with database-optimized defaults.

    Args:
        name: Name for logging, metrics, and event emission.

    Returns:
        CircuitBreaker configured with fail_max=3, reset_timeout=30s.
    """
    return CircuitBreaker(threshold=3, timeout_secs=30.0, provider=name)


# Backward-compatible alias
DatabaseCircuitBreaker = CircuitBreaker
