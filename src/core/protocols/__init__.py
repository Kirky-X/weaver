# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Protocol definitions for repository interfaces.

This module defines Protocol classes that specify the expected interface
for various repositories. Using Protocol enables structural subtyping,
allowing any class that implements the required methods to satisfy the type.

Example:
    from core.protocols.repository import EntityRepository

    def process_entities(repo: EntityRepository) -> None:
        entity = repo.find_entity("name", "type")
        ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import uuid


@runtime_checkable
class EntityRepository(Protocol):
    """Protocol for entity repository implementations.

    Any class implementing these methods can be used as an EntityRepository.
    """

    async def find_entity(
        self,
        canonical_name: str,
        entity_type: str,
    ) -> dict[str, Any] | None:
        """Find an entity by canonical name and type.

        Args:
            canonical_name: The canonical name to search for.
            entity_type: The entity type to match.

        Returns:
            Entity dict if found, None otherwise.
        """
        ...

    async def find_entity_by_id(self, neo4j_id: str) -> dict[str, Any] | None:
        """Find an entity by Neo4j internal ID.

        Args:
            neo4j_id: The Neo4j internal element ID.

        Returns:
            Entity dict if found, None otherwise.
        """
        ...

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
            entity_type: The type of entity.
            description: Optional description for new entities.
            tier: Source tier (1=authoritative, 2+=general).

        Returns:
            The Neo4j internal ID of the entity.
        """
        ...

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

    async def find_entities_batch(
        self,
        names: list[str],
        entity_type: str,
    ) -> list[dict[str, Any]]:
        """Find multiple entities by names in a single query.

        Args:
            names: List of canonical names to search for.
            entity_type: The entity type to match.

        Returns:
            List of entity dicts found.
        """
        ...


@runtime_checkable
class VectorRepository(Protocol):
    """Protocol for vector repository implementations.

    Any class implementing these methods can be used as a VectorRepository.
    """

    async def find_similar(
        self,
        embedding: list[float],
        category: str | None = None,
        threshold: float = 0.80,
        limit: int = 20,
        model_id: str | None = None,
    ) -> list[Any]:
        """Find similar articles using vector similarity.

        Args:
            embedding: Query embedding vector.
            category: Optional category filter.
            threshold: Minimum similarity threshold.
            limit: Maximum number of results.
            model_id: Optional model_id filter.

        Returns:
            List of similar article results.
        """
        ...

    async def find_similar_entities(
        self,
        embedding: list[float],
        threshold: float = 0.85,
        limit: int = 5,
    ) -> list[Any]:
        """Find similar entities using vector similarity.

        Args:
            embedding: Query embedding vector.
            threshold: Minimum similarity threshold.
            limit: Maximum number of results.

        Returns:
            List of similar entity results.
        """
        ...

    async def upsert_article_vectors(
        self,
        article_id: uuid.UUID,
        title_embedding: list[float] | None,
        content_embedding: list[float] | None,
        model_id: str = "text-embedding-3-large",
    ) -> None:
        """Upsert article vectors.

        Args:
            article_id: Article UUID.
            title_embedding: Title embedding vector.
            content_embedding: Content embedding vector.
            model_id: Embedding model ID.
        """
        ...

    async def upsert_entity_vector(
        self,
        neo4j_id: str,
        embedding: list[float],
    ) -> None:
        """Upsert a single entity vector.

        Args:
            neo4j_id: Neo4j entity ID.
            embedding: Entity embedding vector.
        """
        ...


@runtime_checkable
class ArticleRepository(Protocol):
    """Protocol for article repository implementations.

    Any class implementing these methods can be used as an ArticleRepository.
    """

    async def get_by_id(self, article_id: uuid.UUID) -> dict[str, Any] | None:
        """Get an article by ID.

        Args:
            article_id: Article UUID.

        Returns:
            Article dict if found, None otherwise.
        """
        ...

    async def get_existing_urls(self, urls: set[str]) -> set[str]:
        """Check which URLs already exist in the database.

        Args:
            urls: Set of URLs to check.

        Returns:
            Set of URLs that already exist.
        """
        ...

    async def bulk_upsert(
        self,
        states: list[dict[str, Any]],
    ) -> list[uuid.UUID]:
        """Bulk upsert articles.

        Args:
            states: List of pipeline states to persist.

        Returns:
            List of article UUIDs.
        """
        ...

    async def update_persist_status(
        self,
        article_id: uuid.UUID,
        status: str,
    ) -> None:
        """Update article persistence status.

        Args:
            article_id: Article UUID.
            status: New status value.
        """
        ...

    async def mark_failed(self, article_id: uuid.UUID, error: str) -> None:
        """Mark an article as failed.

        Args:
            article_id: Article UUID.
            error: Error message.
        """
        ...
