# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Saga compensation transaction module.

Provides the Saga orchestration pattern for cross-database atomicity
across PostgreSQL, Neo4j, and Redis. Includes:

- CompensationCommand: Abstract base for compensation operations
- PostgresCompensation: Rollback PostgreSQL operations
- Neo4jCompensation: Rollback Neo4j operations
- CompensationExecutor: Execute compensations in reverse order
- SagaOrchestrator: Coordinate saga lifecycle
- SagaLogRepo: Persist saga execution logs
- SagaAlertService: Alert handling for saga/compensation failures
"""

from core.saga.alerts import SagaAlertService
from core.saga.compensation import (
    CompensationCommand,
    Neo4jCompensation,
    PostgresCompensation,
)
from core.saga.executor import CompensationExecutor
from core.saga.orchestrator import SagaOrchestrator
from core.saga.repository import SagaLogRepo

__all__ = [
    "CompensationCommand",
    "CompensationExecutor",
    "Neo4jCompensation",
    "PostgresCompensation",
    "SagaAlertService",
    "SagaLogRepo",
    "SagaOrchestrator",
]
