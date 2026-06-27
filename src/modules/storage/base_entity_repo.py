# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Base entity repository with common entity graph operations.

This module defines the shared interface and common implementations for
entity repositories across different graph databases (Neo4j, LadybugDB).

Architecture:
    - BaseEntityRepo: Abstract base with common method implementations
    - Neo4jEntityRepo: Neo4j-specific optimizations (elementId, datetime())
    - LadybugEntityRepo: LadybugDB-specific (id property, timestamp integers)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.models.shared import EntityView
    from core.protocols import GraphPool

from core.observability import get_logger

log = get_logger(__name__)


class BaseEntityRepo(ABC):
    """Base class for entity repositories.

    Provides common entity CRUD operations and relationship management
    for graph databases. Subclasses handle database-specific syntax
    (elementId vs id property, datetime() vs timestamp integers).

    Args:
        pool: Graph database pool (Neo4j or LadybugDB).
    """

    MAX_MERGE_RETRIES = 3
    DEFAULT_BATCH_SIZE = 1000

    def __init__(self, pool: GraphPool) -> None:
        self._pool = pool

    @abstractmethod
    async def ensure_constraints(self) -> None:
        """Create uniqueness constraints if they don't exist."""
        ...

    # -------------------------------------------------------------------------
    # Core entity operations
    # -------------------------------------------------------------------------

    @abstractmethod
    async def merge_entity(
        self,
        canonical_name: str,
        entity_type: str,
        description: str | None = None,
        tier: int = 2,
    ) -> str:
        """Merge an entity node, creating if not exists.

        Args:
            canonical_name: The canonical/standard name for the entity.
            entity_type: The type of entity (e.g., '人物', '组织机构').
            description: Optional description for new entities.
            tier: Source tier (1=authoritative, 2+=general).

        Returns:
            The entity ID.
        """
        ...

    @abstractmethod
    async def find_entity(
        self,
        canonical_name: str,
        entity_type: str,
    ) -> EntityView | None:
        """Find an entity by canonical name and type.

        Args:
            canonical_name: The canonical name to search for.
            entity_type: The entity type to match.

        Returns:
            EntityView if found, None otherwise.
        """
        ...

    @abstractmethod
    async def find_entity_by_id(self, entity_id: str) -> EntityView | None:
        """Find an entity by its internal ID.

        Args:
            entity_id: The entity's internal ID.

        Returns:
            EntityView if found, None otherwise.
        """
        ...

    async def find_entities_by_ids(
        self,
        entity_ids: list[str],
    ) -> list[EntityView]:
        """Find multiple entities by their IDs.

        Default implementation iterates. Subclasses may override with
        batch query for better performance.

        Args:
            entity_ids: List of entity IDs.

        Returns:
            List of EntityView found.
        """
        if not entity_ids:
            return []
        results = []
        for eid in entity_ids:
            entity = await self.find_entity_by_id(eid)
            if entity:
                results.append(entity)
        return results

    @abstractmethod
    async def add_alias(
        self,
        canonical_name: str,
        entity_type: str,
        alias: str,
    ) -> bool:
        """Add an alias to an existing entity.

        Args:
            canonical_name: The canonical name of the entity.
            entity_type: The type of the entity.
            alias: The alias to add.

        Returns:
            True if alias was added, False if already existed.
        """
        ...

    # -------------------------------------------------------------------------
    # Relationship operations
    # -------------------------------------------------------------------------

    @abstractmethod
    async def merge_relation(
        self,
        from_entity_id: str,
        to_entity_id: str,
        edge_type: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Create or update a typed relationship between two entities.

        Args:
            from_entity_id: Source entity ID.
            to_entity_id: Target entity ID.
            edge_type: Normalised edge type name (e.g. ``PARTNERS_WITH``).
            properties: Optional relationship properties.
        """
        ...

    @abstractmethod
    async def get_entity_relations(
        self,
        canonical_name: str,
        entity_type: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get all relations for an entity.

        Args:
            canonical_name: The canonical name of the entity.
            entity_type: The type of the entity.
            limit: Maximum number of relations to return.

        Returns:
            List of relation dictionaries.
        """
        ...

    # -------------------------------------------------------------------------
    # Entity listing and cleanup
    # -------------------------------------------------------------------------

    @abstractmethod
    async def list_all_entity_ids(self) -> set[str]:
        """List all entity IDs.

        Returns:
            Set of all entity internal IDs.
        """
        ...

    @abstractmethod
    async def list_all_entity_names(self) -> set[str]:
        """List all entity canonical names.

        REM-001: Used by cleanup_orphan_entity_vectors to compare against
        entity_vectors.neo4j_id (which stores entity names, not graph IDs).
        Comparing by name avoids the ID namespace mismatch between
        entity_vectors (names) and list_all_entity_ids (graph internal IDs).

        Returns:
            Set of all entity canonical names.
        """
        ...

    async def delete_orphan_entities(self) -> int:
        """Delete entities that have no relationships.

        Returns:
            Number of entities deleted.
        """
        # Default implementation using list + delete
        orphan_ids = await self._list_orphan_ids()
        for eid in orphan_ids:
            await self._pool.execute_query(
                self._delete_entity_query(),
                self._entity_id_params(eid),
            )
        return len(orphan_ids)

    async def count_orphan_entities(self) -> int:
        """Count orphan entities.

        Returns:
            Number of orphan entities.
        """
        query = self._orphan_count_query()
        result = await self._pool.execute_query(query)
        return result[0].get("count", 0) if result else 0

    # -------------------------------------------------------------------------
    # Mentions (article-entity relationships)
    # -------------------------------------------------------------------------

    @abstractmethod
    async def merge_mentions_relation(
        self,
        article_id: str,
        entity_id: str,
        role: str | None = None,
    ) -> None:
        """Create a MENTIONS relationship from article to entity.

        Args:
            article_id: The article's ID.
            entity_id: The entity's ID.
            role: Optional role (e.g., 'subject', 'object').
        """
        ...

    @abstractmethod
    async def get_relation_types(
        self,
        canonical_name: str,
        entity_type: str,
    ) -> list[dict[str, Any]]:
        """Get all relation types for an entity.

        Args:
            canonical_name: The canonical name of the entity.
            entity_type: The type of the entity.

        Returns:
            List of dicts with relation type information.
        """
        ...

    @abstractmethod
    async def find_by_relation_types(
        self,
        canonical_name: str,
        entity_type: str | None = None,
        relation_types: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Find related entities by relation types.

        Args:
            canonical_name: The canonical name of the entity.
            entity_type: The type of the entity (optional).
            relation_types: Optional list of relationship type names to filter.
            limit: Maximum number of results.

        Returns:
            List of related-entity dicts.
        """
        ...

    # -------------------------------------------------------------------------
    # Batch operations
    # -------------------------------------------------------------------------

    async def merge_entities_batch(
        self,
        entities: list[dict[str, Any]],
        batch_size: int | None = None,
    ) -> dict[str, int]:
        """Merge multiple entities.

        Default implementation iterates. Subclasses should override
        with batch query for better performance.

        Args:
            entities: List of entity dicts.
            batch_size: Batch size (default: DEFAULT_BATCH_SIZE).

        Returns:
            Dict with 'created' and 'updated' counts.
        """
        created = 0
        updated = 0
        for entity in entities:
            existing = await self.find_entity(
                entity.get("canonical_name", ""),
                entity.get("entity_type", ""),
            )
            if existing:
                updated += 1
            else:
                await self.merge_entity(
                    entity.get("canonical_name", ""),
                    entity.get("entity_type", ""),
                    entity.get("description"),
                    entity.get("tier", 2),
                )
                created += 1
        return {"created": created, "updated": updated}

    async def add_aliases_batch(
        self,
        aliases: list[dict[str, Any]],
        batch_size: int | None = None,
    ) -> int:
        """Add aliases to multiple entities.

        Default implementation iterates. Subclasses may override with batch query.

        Args:
            aliases: List of dicts with 'canonical_name', 'type', 'alias'.
            batch_size: Batch size (default: DEFAULT_BATCH_SIZE).

        Returns:
            Number of entities updated.
        """
        return sum(
            await self.add_alias(a.get("canonical_name", ""), a.get("type", ""), a.get("alias", ""))
            for a in aliases
        )

    @abstractmethod
    async def merge_relations_batch(
        self,
        relations: list[dict[str, Any]],
        batch_size: int | None = None,
    ) -> int:
        """Merge multiple relationships.

        Args:
            relations: List of relation dicts.
            batch_size: Batch size.

        Returns:
            Total number of relationships created/updated.
        """
        ...

    @abstractmethod
    async def merge_mentions_batch(
        self,
        mentions: list[dict[str, Any]],
        batch_size: int | None = None,
    ) -> int:
        """Merge multiple MENTIONS relationships.

        Args:
            mentions: List of mention dicts.
            batch_size: Batch size.

        Returns:
            Number of MENTIONS relationships created.
        """
        ...

    @abstractmethod
    async def find_entities_batch(
        self,
        names: list[str],
        entity_type: str,
    ) -> list[EntityView]:
        """Find multiple entities by names.

        Args:
            names: List of canonical names to search for.
            entity_type: The entity type to match.

        Returns:
            List of EntityView found.
        """
        ...

    @abstractmethod
    async def find_entities_by_keys(
        self,
        keys: list[dict[str, str]],
    ) -> list[EntityView]:
        """Find multiple entities by (canonical_name, type) keys.

        Args:
            keys: List of dicts with 'canonical_name' and 'type'.

        Returns:
            List of EntityView found.
        """
        ...

    @abstractmethod
    async def delete_entities_batch(
        self,
        entity_ids: list[str],
        batch_size: int | None = None,
    ) -> int:
        """Delete multiple entities by their IDs.

        Args:
            entity_ids: List of entity IDs.
            batch_size: Batch size.

        Returns:
            Number of entities deleted.
        """
        ...

    # -------------------------------------------------------------------------
    # Neighborhood and linking
    # -------------------------------------------------------------------------

    @abstractmethod
    async def get_entity_neighborhood(
        self,
        entity_name: str,
        entity_type: str | None = None,
        hops: int = 2,
        limit: int = 50,
    ) -> dict[str, Any] | None:
        """Get the neighborhood of an entity in the graph.

        Args:
            entity_name: Canonical name of the entity.
            entity_type: Optional entity type for disambiguation.
            hops: Number of hops for neighborhood expansion.
            limit: Maximum number of related items to return.

        Returns:
            Dictionary with center, events, related_entities, relations, hops.
            Returns None if entity not found.
        """
        ...

    async def link_entities(
        self,
        event: object,
        entities: list[dict[str, Any]],
    ) -> int:
        """Link an event (article) to its extracted entities.

        Args:
            event: EventNode instance with id (article UUID).
            entities: List of entity dicts with 'id' or 'neo4j_id' field.

        Returns:
            Number of entities linked.
        """
        from modules.memory.core.event_node import EventNode

        if not isinstance(event, EventNode):
            return 0

        linked = 0
        for entity in entities:
            entity_id = entity.get("id") or entity.get("neo4j_id")
            if not entity_id:
                continue
            try:
                await self.merge_mentions_relation(
                    article_id=event.id,
                    entity_id=str(entity_id),
                )
                linked += 1
            except Exception as exc:
                log.warning(
                    "link_entity_failed",
                    event_id=event.id,
                    entity_id=str(entity_id),
                    error=str(exc),
                )
        return linked

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    @staticmethod
    def _chunk(items: list[Any], size: int) -> Iterator[list[Any]]:
        """Split items into chunks of specified size."""
        for i in range(0, len(items), size):
            yield items[i : i + size]

    # -------------------------------------------------------------------------
    # Abstract methods for subclass-specific queries
    # -------------------------------------------------------------------------

    @abstractmethod
    async def _list_orphan_ids(self) -> list[str]:
        """List IDs of orphan entities. Must be implemented by subclass."""
        ...

    @abstractmethod
    def _delete_entity_query(self) -> str:
        """Return the query to delete a single entity by ID."""
        ...

    @abstractmethod
    def _entity_id_params(self, entity_id: str) -> dict[str, Any]:
        """Return the params dict for deleting an entity by ID."""
        ...

    @abstractmethod
    def _orphan_count_query(self) -> str:
        """Return the query to count orphan entities."""
        ...
