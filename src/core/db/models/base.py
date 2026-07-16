# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Foundation classes for SQLAlchemy 2.0 ORM models.

Provides the declarative base, JSON-compatible type decorator, and shared
enum types used across all weaver ORM models.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import JSON, TypeDecorator


class JSONCompatible(TypeDecorator):
    """TypeDecorator that uses JSONB for PostgreSQL and JSON for other dialects.

    DuckDB and SQLite don't support JSONB, only JSON. This decorator
    automatically selects the appropriate type based on the database dialect.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            # Use JSONB for PostgreSQL
            return JSONB().dialect_impl(dialect)
        # Use plain JSON for DuckDB, SQLite, etc.
        return JSON().dialect_impl(dialect)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    type_annotation_map = {
        dict[str, Any]: JSONCompatible,
        list[str]: ARRAY(Text),
        list[uuid.UUID]: ARRAY(UUID(as_uuid=True)),
    }


# ── Enum Types ───────────────────────────────────────────────


class CategoryType(str, enum.Enum):
    POLITICS = "政治"
    MILITARY = "军事"
    ECONOMY = "经济"
    TECHNOLOGY = "科技"
    SOCIETY = "社会"
    CULTURE = "文化"
    SPORTS = "体育"
    INTERNATIONAL = "国际"
    OTHER = "其他"


class PersistStatus(str, enum.Enum):
    """Persist status for articles.

    States:
        PENDING: Initial state after article creation.
        PROCESSING: Traditional pipeline processing in progress.
        PG_DONE: PostgreSQL write successful.
        NEO4J_DONE: All writes complete (terminal success state for Neo4j).
        LADYBUG_DONE: All writes complete (terminal success state for LadybugDB).
        NEO4J_FAILED: Neo4j write failed (retryable).
        FAILED: Final failure state (retryable).

    Saga States (for cross-database transactions):
        SAGA_STARTED: Saga transaction initiated.
        SAGA_PG_WRITING: PostgreSQL write phase of Saga.
        SAGA_NEO4J_WRITING: Neo4j write phase of Saga.
        SAGA_COMPENSATING: Saga compensation in progress.
        SAGA_COMPENSATED: Saga compensation complete.
        SAGA_COMPLETED: Saga transaction fully complete (terminal success state).
    """

    PENDING = "pending"
    PROCESSING = "processing"
    PG_DONE = "pg_done"
    NEO4J_DONE = "neo4j_done"
    LADYBUG_DONE = "ladybug_done"
    NEO4J_FAILED = "neo4j_failed"
    SAGA_STARTED = "saga_started"
    SAGA_PG_WRITING = "saga_pg_writing"
    SAGA_NEO4J_WRITING = "saga_neo4j_writing"
    SAGA_COMPENSATING = "saga_compensating"
    SAGA_COMPENSATED = "saga_compensated"
    SAGA_COMPLETED = "saga_completed"
    FAILED = "failed"

    @classmethod
    def is_valid_transition(
        cls,
        from_status: PersistStatus,
        to_status: PersistStatus,
    ) -> bool:
        """Validate if a status transition is allowed.

        Valid transitions:
        - PENDING → PROCESSING, FAILED, SAGA_STARTED
        - PROCESSING → PG_DONE, FAILED
        - PG_DONE → NEO4J_DONE, LADYBUG_DONE, NEO4J_FAILED, FAILED
        - NEO4J_FAILED → PENDING, PG_DONE (allows retry)
        - SAGA_STARTED → SAGA_PG_WRITING, FAILED
        - SAGA_PG_WRITING → SAGA_NEO4J_WRITING, SAGA_COMPENSATING
        - SAGA_NEO4J_WRITING → SAGA_COMPLETED, SAGA_COMPENSATING
        - SAGA_COMPENSATING → SAGA_COMPENSATED, FAILED
        - SAGA_COMPENSATED → PENDING (allows retry)
        - SAGA_COMPLETED is terminal
        - FAILED → PENDING (allows retry), NEO4J_DONE, LADYBUG_DONE (allows recovery after graph write success)
        - NEO4J_DONE is terminal
        - LADYBUG_DONE is terminal

        Args:
            from_status: Current status.
            to_status: Target status.

        Returns:
            True if the transition is valid, False otherwise.
        """
        if from_status == to_status:
            return True

        valid_transitions = {
            cls.PENDING: {
                cls.PROCESSING,
                cls.FAILED,
                cls.SAGA_STARTED,
                cls.LADYBUG_DONE,
                cls.NEO4J_DONE,
            },
            cls.PROCESSING: {cls.PG_DONE, cls.FAILED},
            cls.PG_DONE: {cls.NEO4J_DONE, cls.LADYBUG_DONE, cls.NEO4J_FAILED, cls.FAILED},
            cls.NEO4J_FAILED: {cls.PENDING, cls.PG_DONE},
            cls.SAGA_STARTED: {cls.SAGA_PG_WRITING, cls.FAILED},
            cls.SAGA_PG_WRITING: {cls.SAGA_NEO4J_WRITING, cls.SAGA_COMPENSATING},
            cls.SAGA_NEO4J_WRITING: {cls.SAGA_COMPLETED, cls.SAGA_COMPENSATING},
            cls.SAGA_COMPENSATING: {cls.SAGA_COMPENSATED, cls.FAILED},
            cls.SAGA_COMPENSATED: {cls.PENDING},
            cls.SAGA_COMPLETED: set(),
            cls.FAILED: {cls.PENDING, cls.NEO4J_DONE, cls.LADYBUG_DONE},
            cls.NEO4J_DONE: set(),
            cls.LADYBUG_DONE: set(),
        }

        allowed = valid_transitions.get(from_status, set())
        return to_status in allowed

    @classmethod
    def completed_statuses(cls) -> frozenset[PersistStatus]:
        """Return the set of statuses that indicate article processing is complete.

        Includes all terminal success states and PG_DONE (intermediate success).
        Used for queries that need to find "completed" articles regardless of
        which graph database backend was used.
        """
        return frozenset({cls.PG_DONE, cls.NEO4J_DONE, cls.LADYBUG_DONE, cls.SAGA_COMPLETED})

    @classmethod
    def is_terminal(cls, status: PersistStatus) -> bool:
        """Check if a status is terminal (no outgoing transitions except self).

        Args:
            status: Status to check.

        Returns:
            True if the status is terminal.
        """
        return status in {cls.NEO4J_DONE, cls.LADYBUG_DONE, cls.SAGA_COMPLETED}

    @classmethod
    def allows_retry(cls, status: PersistStatus) -> bool:
        """Check if a status allows retry (can transition to PENDING).

        Args:
            status: Status to check.

        Returns:
            True if the status allows retry.
        """
        return status in {cls.FAILED, cls.SAGA_COMPENSATED, cls.NEO4J_FAILED}


class EmotionType(str, enum.Enum):
    OPTIMISTIC = "乐观"
    INSPIRED = "振奋"
    EXCITED = "兴奋"
    EXPECTANT = "期待"
    CALM = "平静"
    OBJECTIVE = "客观"
    WORRIED = "担忧"
    PESSIMISTIC = "悲观"
    ANGRY = "愤怒"
    PANIC = "恐慌"


class VectorType(str, enum.Enum):
    TITLE = "title"
    CONTENT = "content"
