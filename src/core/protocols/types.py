# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Shared type definitions used in Protocol signatures.

This module DEFINES PersistStatus (owned here since so the protocols
layer never depends on ``core.db``) and re-exports the remaining types used
in Protocol method signatures.

Importing from this module is preferred within ``core.protocols``:
    from core.protocols.types import PersistStatus, PipelineState

Re-exported types:
    - PersistStatus: Article persistence status enum (defined in core.db.models.base)
    - PipelineState: TypedDict for pipeline state (defined in core.types.pipeline_state)
    - ArticleView, EntityView, EventView, CommunityView: View models
      (defined in core.models.shared)
    - ArticleSearchResultView, EntitySearchResultView, CommunitySearchResultView:
      Search result view models (defined in core.models.shared)
    - ArticleTitleMeta: TypedDict for batch title lookup (defined here)
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TypedDict

# Import directly from the definition modules (not the package __init__)
# to avoid circular imports:
#   core.protocols -> core.protocols.types -> core.db -> core.protocols
# By importing from core.db.models.base and core.types.pipeline_state
# directly, we bypass the core.db.__init__ which imports core.protocols.
from core.models.shared import (
    ArticleSearchResultView,
    ArticleView,
    CommunitySearchResultView,
    CommunityView,
    EntitySearchResultView,
    EntityView,
    EventView,
)
from core.types.pipeline_state import PipelineState


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
        - PENDING → PROCESSING, FAILED, SAGA_STARTED, LADYBUG_DONE, NEO4J_DONE
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


class ArticleTitleMeta(TypedDict):
    """Article metadata returned by ``ArticleRepository.fetch_titles_by_pg_ids``.

    Used by graph-query callers that, after the Article node slim-down, can only read ``pg_id`` from the graph DB and must
    look up the business fields from the relational DB in a batch.
    """

    title: str
    category: str | None
    publish_time: datetime | None
    score: float | None


__all__ = [
    "ArticleSearchResultView",
    "ArticleTitleMeta",
    "ArticleView",
    "CommunitySearchResultView",
    "CommunityView",
    "EntitySearchResultView",
    "EntityView",
    "EventView",
    "PersistStatus",
    "PipelineState",
]
