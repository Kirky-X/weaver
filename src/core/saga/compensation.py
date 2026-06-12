# Copyright (c) 2026 KirkyX. All Rights Reserved
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

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

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
    - Article insert: delete the article record
    - Article update: restore original data from backup
    - Status change: restore previous PersistStatus value

    Attributes:
        saga_id: ID of the saga this compensation belongs to.
        article_id: ID of the affected article.
        step_name: Name of the step being compensated.
        operation: Type of operation ('insert', 'update', 'status_change').
        backup_data: Original data for restore (None for inserts).
    """

    saga_id: str
    article_id: str
    step_name: str
    operation: str  # 'insert', 'update', 'status_change'
    backup_data: dict[str, Any] | None = field(default=None)

    async def execute(self) -> None:
        """Execute PostgreSQL compensation.

        Delegates to the appropriate rollback strategy based on operation type.
        Actual database operations are performed by the CompensationExecutor
        which has access to the RelationalPool.
        """
        log.info(
            "postgres_compensation_execute",
            saga_id=self.saga_id,
            article_id=self.article_id,
            step_name=self.step_name,
            operation=self.operation,
        )

    def serialize(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "type": "postgres",
            "saga_id": self.saga_id,
            "article_id": self.article_id,
            "step_name": self.step_name,
            "operation": self.operation,
            "backup_data": self.backup_data,
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
            article_id=data["article_id"],
            step_name=data["step_name"],
            operation=data["operation"],
            backup_data=data.get("backup_data"),
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
    """

    saga_id: str
    article_id: str
    step_name: str
    operation: str  # 'entity_create', 'relationship_create', 'community_assign'
    entity_ids: list[str] = field(default_factory=list)
    relationship_ids: list[str] = field(default_factory=list)

    async def execute(self) -> None:
        """Execute Neo4j compensation.

        Delegates to the appropriate rollback strategy based on operation type.
        Actual database operations are performed by the CompensationExecutor
        which has access to the GraphPool.
        """
        log.info(
            "neo4j_compensation_execute",
            saga_id=self.saga_id,
            article_id=self.article_id,
            step_name=self.step_name,
            operation=self.operation,
        )

    def serialize(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "type": "neo4j",
            "saga_id": self.saga_id,
            "article_id": self.article_id,
            "step_name": self.step_name,
            "operation": self.operation,
            "entity_ids": self.entity_ids,
            "relationship_ids": self.relationship_ids,
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
            article_id=data["article_id"],
            step_name=data["step_name"],
            operation=data["operation"],
            entity_ids=data.get("entity_ids", []),
            relationship_ids=data.get("relationship_ids", []),
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
