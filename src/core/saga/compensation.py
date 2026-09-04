# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Compensation command classes for Saga rollback operations.

Implements the Command pattern for compensation transactions, enabling
each saga step to define its own rollback logic. Commands are serializable
for storage in saga_logs.compensation_data.

Implements:
    - CompensationCommand: Abstract base protocol
    - PostgresCompensation: Rollback PostgreSQL operations
    - Neo4jCompensation: Rollback Neo4j operations
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.db import PersistStatus
from core.observability import get_logger

log = get_logger(__name__)


class CompensationCommand(ABC):
    """Abstract base class for compensation operations.

    Each saga step that modifies state must provide a corresponding
    compensation command that can undo the operation. Commands are
    idempotent: executing the same compensation twice has no additional
    effect.
    """

    @abstractmethod
    async def execute(self) -> None:
        """Execute the compensation operation.

        Must be idempotent — safe to call multiple times.
        """

    @abstractmethod
    def serialize(self) -> dict[str, Any]:
        """Serialize compensation data for storage in saga_logs.

        Returns:
            Dict with at least 'type' key for deserialization routing.
        """


@dataclass
class PostgresCompensation(CompensationCommand):
    """Compensation command for PostgreSQL operations.

    Supports rollback of:
    - Article insert: mark articles as failed, clean up vectors
    - Article update: restore original data from backup
    - Status change: restore previous PersistStatus value

    Attributes:
        saga_id: ID of the saga this compensation belongs to.
        article_id: ID of the affected article (single-article operations).
        step_name: Name of the step being compensated.
        operation: Type of operation ('insert', 'update', 'status_change').
        backup_data: Original data for restore (None for inserts).
        article_ids: Batch article IDs to compensate (UUID or str).
        vector_article_ids: Batch vector article IDs to clean up (UUID or str).
    """

    saga_id: str
    article_id: str
    step_name: str
    operation: str  # 'insert', 'update', 'status_change'
    backup_data: dict[str, Any] | None = field(default=None)
    article_ids: list[str] = field(default_factory=list)
    vector_article_ids: list[str] = field(default_factory=list)

    # Transient fields — not serialized, injected at runtime
    _relational_pool: Any = field(default=None, repr=False, compare=False)
    _article_repo: Any = field(default=None, repr=False, compare=False)
    _vector_repo: Any = field(default=None, repr=False, compare=False)

    def inject_pools(
        self,
        relational_pool: Any = None,
        article_repo: Any = None,
        vector_repo: Any = None,
        **kwargs: Any,
    ) -> None:
        """Inject database pool dependencies at runtime."""
        self._relational_pool = relational_pool
        self._article_repo = article_repo
        self._vector_repo = vector_repo

    async def execute(self) -> None:
        """Execute PostgreSQL compensation.

        Performs actual database rollback using injected pool dependencies.
        """
        log.info(
            "postgres_compensation_execute",
            saga_id=self.saga_id,
            article_id=self.article_id,
            step_name=self.step_name,
            operation=self.operation,
            article_ids_count=len(self.article_ids),
            vector_article_ids_count=len(self.vector_article_ids),
        )

        if self.operation == "insert":
            # Mark articles as failed
            if self.article_ids and self._article_repo:
                error_msg = f"Saga compensation: {self.step_name} failed"
                for aid in self.article_ids:
                    try:
                        article_uuid = aid if isinstance(aid, uuid.UUID) else uuid.UUID(str(aid))
                        await self._article_repo.mark_failed(
                            article_uuid,
                            error_msg,
                        )
                    except (ValueError, AttributeError) as exc:
                        log.warning(
                            "postgres_compensation_invalid_article_id",
                            article_id=str(aid),
                            error=str(exc),
                        )

            # Clean up article vectors
            if self.vector_article_ids and self._vector_repo:
                try:
                    vector_uuids = [
                        vid if isinstance(vid, uuid.UUID) else uuid.UUID(str(vid))
                        for vid in self.vector_article_ids
                    ]
                    deleted = await self._vector_repo.delete_article_vectors_by_article_ids(
                        vector_uuids,
                    )
                    log.info(
                        "postgres_compensation_vectors_cleaned",
                        count=deleted,
                    )
                except Exception as exc:
                    log.warning(
                        "postgres_compensation_vector_cleanup_failed",
                        error=str(exc),
                    )

        elif self.operation == "status_change":
            # Restore previous status (mark as FAILED)
            if self.article_ids and self._article_repo:
                for aid in self.article_ids:
                    try:
                        article_uuid = aid if isinstance(aid, uuid.UUID) else uuid.UUID(str(aid))
                        await self._article_repo.update_persist_status(
                            article_uuid,
                            PersistStatus.FAILED,
                        )
                    except (ValueError, AttributeError) as exc:
                        log.warning(
                            "postgres_compensation_status_update_failed",
                            article_id=str(aid),
                            error=str(exc),
                        )

    def serialize(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict.

        UUID objects in article_ids/vector_article_ids are converted to
        strings for JSON compatibility.
        """
        return {
            "type": "postgres",
            "saga_id": self.saga_id,
            "article_id": self.article_id,
            "step_name": self.step_name,
            "operation": self.operation,
            "backup_data": self.backup_data,
            "article_ids": [str(a) for a in self.article_ids],
            "vector_article_ids": [str(v) for v in self.vector_article_ids],
        }

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> PostgresCompensation:
        """Deserialize from dict.

        Args:
            data: Dict from saga_logs.compensation_data.

        Returns:
            PostgresCompensation instance.
        """
        return cls(
            saga_id=data["saga_id"],
            article_id=data.get("article_id", ""),
            step_name=data["step_name"],
            operation=data["operation"],
            backup_data=data.get("backup_data"),
            article_ids=data.get("article_ids", []),
            vector_article_ids=data.get("vector_article_ids", []),
        )


@dataclass
class Neo4jCompensation(CompensationCommand):
    """Compensation command for Neo4j operations.

    Supports rollback of:
    - Entity creation: delete the entity node
    - Relationship creation: delete the relationship
    - Community assignment: remove entity from community

    Attributes:
        saga_id: ID of the saga this compensation belongs to.
        article_id: ID of the affected article.
        step_name: Name of the step being compensated.
        operation: Type of operation ('entity_create', 'relationship_create', 'community_assign').
        entity_ids: IDs of entities to delete (for entity_create).
        relationship_ids: IDs of relationships to delete (for relationship_create).
        article_ids: Batch article IDs to mark as FAILED on Phase 2 rollback.
    """

    saga_id: str
    article_id: str
    step_name: str
    operation: str  # 'entity_create', 'relationship_create', 'community_assign'
    entity_ids: list[str] = field(default_factory=list)
    relationship_ids: list[str] = field(default_factory=list)
    article_ids: list[str] = field(default_factory=list)

    # Transient fields — not serialized, injected at runtime
    _graph_pool: Any = field(default=None, repr=False, compare=False)
    _article_repo: Any = field(default=None, repr=False, compare=False)

    def inject_pools(
        self,
        graph_pool: Any = None,
        article_repo: Any = None,
        **kwargs: Any,
    ) -> None:
        """Inject database pool dependencies at runtime."""
        self._graph_pool = graph_pool
        self._article_repo = article_repo

    async def execute(self) -> None:
        """Execute Neo4j compensation.

        Marks associated articles as FAILED when Phase 2 (Neo4j) fails.
        """
        log.info(
            "neo4j_compensation_execute",
            saga_id=self.saga_id,
            article_id=self.article_id,
            step_name=self.step_name,
            operation=self.operation,
            article_ids_count=len(self.article_ids),
        )

        if self.article_ids and self._article_repo:
            error_msg = f"Saga compensation: {self.step_name} failed"
            for aid in self.article_ids:
                try:
                    article_uuid = aid if isinstance(aid, uuid.UUID) else uuid.UUID(str(aid))
                    await self._article_repo.update_persist_status(
                        article_uuid,
                        PersistStatus.FAILED,
                    )
                except (ValueError, AttributeError) as exc:
                    log.warning(
                        "neo4j_compensation_status_update_failed",
                        article_id=str(aid),
                        error=str(exc),
                    )

    def serialize(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict.

        UUID objects in article_ids are converted to strings.
        """
        return {
            "type": "neo4j",
            "saga_id": self.saga_id,
            "article_id": self.article_id,
            "step_name": self.step_name,
            "operation": self.operation,
            "entity_ids": self.entity_ids,
            "relationship_ids": self.relationship_ids,
            "article_ids": [str(a) for a in self.article_ids],
        }

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> Neo4jCompensation:
        """Deserialize from dict.

        Args:
            data: Dict from saga_logs.compensation_data.

        Returns:
            Neo4jCompensation instance.
        """
        return cls(
            saga_id=data["saga_id"],
            article_id=data.get("article_id", ""),
            step_name=data["step_name"],
            operation=data["operation"],
            entity_ids=data.get("entity_ids", []),
            relationship_ids=data.get("relationship_ids", []),
            article_ids=data.get("article_ids", []),
        )


def deserialize_compensation(data: dict[str, Any]) -> CompensationCommand:
    """Deserialize a compensation command from stored data.

    Routes to the correct concrete class based on the 'type' field.

    Args:
        data: Dict from saga_logs.compensation_data.

    Returns:
        Concrete CompensationCommand instance.

    Raises:
        ValueError: If the type field is missing or unknown.
    """
    comp_type = data.get("type")
    if comp_type == "postgres":
        return PostgresCompensation.deserialize(data)
    elif comp_type == "neo4j":
        return Neo4jCompensation.deserialize(data)
    else:
        raise ValueError(f"Unknown compensation type: {comp_type}")
