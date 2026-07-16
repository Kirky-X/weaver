# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Abstract graph repository using QueryBuilder pattern.

Provides database-agnostic graph operations by delegating query building
to GraphQueryBuilder implementations.

Read operations are composed from four reader classes, each with a single
responsibility:
- GraphEntityReader: entity-centric reads
- GraphArticleReader: article-centric reads
- GraphVisualizer: visualization reads
- GraphTraverser: multi-hop traversal

This class owns the shared fallback-aware query execution and delegates
the read methods to the composed readers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.db.graph_query_builders import GraphQueryBuilder
from core.observability import get_logger
from modules.storage.graph_readers.article import GraphArticleReader
from modules.storage.graph_readers.entity import GraphEntityReader
from modules.storage.graph_readers.traverser import GraphTraverser
from modules.storage.graph_readers.visualizer import GraphVisualizer

if TYPE_CHECKING:
    from core.protocols import GraphPool

log = get_logger(__name__)


class GraphRepository:
    """Database-agnostic graph repository.

    Handles entity and article graph operations using the QueryBuilder pattern
    to abstract Neo4j/LadybugDB syntax differences.

    Read operations are delegated to four composed reader instances. This
    class retains the shared fallback-aware query execution logic and the
    primary database connection state.

    Supports automatic fallback: if the primary database (Neo4j) returns
    empty results, queries the fallback (LadybugDB).

    Args:
        pool: Primary graph database pool (Neo4j or LadybugDB).
        query_builder: Database-specific query builder for primary.
        fallback_pool_factory: Optional factory function for lazy fallback pool creation.
        fallback_query_builder: Optional query builder for fallback.
    """

    def __init__(
        self,
        pool: GraphPool,
        query_builder: GraphQueryBuilder,
        fallback_pool_factory: callable | None = None,
        fallback_query_builder: GraphQueryBuilder | None = None,
    ) -> None:
        self._pool = pool
        self._query_builder = query_builder
        self._fallback_pool_factory = fallback_pool_factory
        self._fallback_query_builder = fallback_query_builder
        self._fallback_pool: GraphPool | None = None  # Lazy-initialized

        # Compose readers, injecting shared dependencies. The execute_fn
        # callable binds _execute_with_fallback so all readers share the
        # same fallback pool state owned by this repository.
        self._entity_reader = GraphEntityReader(pool, query_builder, self._execute_with_fallback)
        self._article_reader = GraphArticleReader(pool, query_builder, self._execute_with_fallback)
        self._visualizer = GraphVisualizer(pool, query_builder, self._execute_with_fallback)
        self._traverser = GraphTraverser(pool, query_builder, self._execute_with_fallback)

    @property
    def database_type(self) -> str:
        """Get the database type."""
        return self._query_builder.database_type.value

    async def _get_fallback_pool(self) -> GraphPool | None:
        """Get or lazily initialize the fallback pool with schema."""
        if self._fallback_pool is None and self._fallback_pool_factory is not None:
            pool = self._fallback_pool_factory()
            await pool.startup()

            # Initialize LadybugDB schema (create EventNode, CAUSES, etc.)
            from core.db.ladybug_schema import initialize_ladybug_schema

            await initialize_ladybug_schema(pool)
            log.info("ladybug_schema_initialized_for_fallback")

            self._fallback_pool = pool
            log.info("graph_repo_fallback_initialized")
        return self._fallback_pool

    async def _execute_with_fallback(
        self,
        build_query_fn: Any,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute query on primary, fallback if empty."""
        query = build_query_fn(self._query_builder)
        result = await self._pool.execute_query(query, params or {})
        if result or self._fallback_query_builder is None:
            return result
        try:
            fallback_pool = await self._get_fallback_pool()
            if fallback_pool is None:
                return result
            fb_query = build_query_fn(self._fallback_query_builder)
            return await fallback_pool.execute_query(fb_query, params or {})
        except Exception as exc:
            log.warning("graph_repo_fallback_failed", error=str(exc))
            return result

    # ── Entity Operations (delegated to GraphEntityReader) ──────────

    async def get_entity(self, canonical_name: str) -> dict[str, Any] | None:
        """Get entity by canonical name.

        Args:
            canonical_name: Entity canonical name.

        Returns:
            Entity dict or None if not found.
        """
        return await self._entity_reader.get_entity(canonical_name)

    async def get_entity_relations(
        self, canonical_name: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get relationships from an entity.

        Args:
            canonical_name: Entity canonical name.
            limit: Maximum number of relationships.

        Returns:
            List of relationship dicts.
        """
        return await self._entity_reader.get_entity_relations(canonical_name, limit)

    async def get_related_entities(
        self, canonical_name: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get entities mentioned in same articles.

        Args:
            canonical_name: Entity canonical name.
            limit: Maximum number of entities.

        Returns:
            List of entity dicts.
        """
        return await self._entity_reader.get_related_entities(canonical_name, limit)

    async def get_entity_articles(
        self, canonical_name: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get articles mentioning an entity.

        Args:
            canonical_name: Entity canonical name.
            limit: Maximum number of articles.

        Returns:
            List of article dicts.
        """
        return await self._article_reader.get_entity_articles(canonical_name, limit)

    # ── Article Graph Operations (delegated to GraphArticleReader) ───

    async def get_article(self, article_id: str) -> dict[str, Any] | None:
        """Get article node from graph.

        Args:
            article_id: Article UUID (pg_id).

        Returns:
            Article dict or None if not found.
        """
        return await self._article_reader.get_article(article_id)

    async def get_article_entities(self, article_id: str) -> list[dict[str, Any]]:
        """Get entities mentioned in an article.

        Args:
            article_id: Article UUID.

        Returns:
            List of entity dicts.
        """
        return await self._article_reader.get_article_entities(article_id)

    async def get_article_relationships(self, article_id: str) -> list[dict[str, Any]]:
        """Get relationships between entities in an article.

        Args:
            article_id: Article UUID.

        Returns:
            List of relationship dicts.
        """
        return await self._article_reader.get_article_relationships(article_id)

    async def get_related_articles(self, article_id: str) -> list[dict[str, Any]]:
        """Get related articles.

        Args:
            article_id: Article UUID.

        Returns:
            List of article dicts.
        """
        return await self._article_reader.get_related_articles(article_id)

    # ── Relation Type Operations (delegated to GraphEntityReader) ────

    async def get_relation_types(
        self, entity_name: str, entity_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all relation types for an entity.

        Args:
            entity_name: Entity canonical name.
            entity_type: Optional entity type filter. When None, matches
                by canonical_name only (cross-type lookup).

        Returns:
            List of relation type summaries.
        """
        return await self._entity_reader.get_relation_types(entity_name, entity_type)

    async def find_by_relation_types(
        self,
        entity_name: str,
        entity_type: str | None = None,
        relation_types: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Find related entities by relation types.

        Args:
            entity_name: Entity canonical name.
            entity_type: Entity type (optional, matched by canonical_name only if None).
            relation_types: Optional list of relation types to filter.
            limit: Maximum number of results.

        Returns:
            List of related entity dicts with computed co-occurrence weight.
        """
        return await self._entity_reader.find_by_relation_types(
            entity_name, entity_type, relation_types, limit
        )

    # ── Visualization Operations (delegated to GraphVisualizer) ──────

    async def get_visualization_nodes(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get nodes for graph visualization.

        Args:
            limit: Maximum number of nodes to return.

        Returns:
            List of node dicts with id, label, type, description, and degree.
        """
        return await self._visualizer.get_visualization_nodes(limit)

    async def get_visualization_edges(
        self, node_ids: list[str], edge_limit: int = 300
    ) -> list[dict[str, Any]]:
        """Get edges for graph visualization.

        Args:
            node_ids: List of node canonical names to filter edges.
            edge_limit: Maximum number of edges to return.

        Returns:
            List of edge dicts with source, target, relation_type, and weight.
        """
        return await self._visualizer.get_visualization_edges(node_ids, edge_limit)

    async def get_subgraph_nodes(
        self,
        center_entity: str,
        hop_pattern: str,
        include_types: list[str] | None = None,
        exclude_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get nodes for subgraph extraction around a center entity.

        Args:
            center_entity: Center entity canonical name.
            hop_pattern: Hop pattern like '*1..1', '*1..2', etc.
            include_types: Optional list of entity types to include.
            exclude_types: Optional list of entity types to exclude (applied in Python).

        Returns:
            List of node dicts with id, label, type, and description.
        """
        return await self._visualizer.get_subgraph_nodes(
            center_entity, hop_pattern, include_types, exclude_types
        )

    async def get_subgraph_edges(self, node_ids: list[str]) -> list[dict[str, Any]]:
        """Get edges for subgraph visualization.

        Args:
            node_ids: List of node canonical names to filter edges.

        Returns:
            List of edge dicts with source, target, relation_type, and weight.
        """
        return await self._visualizer.get_subgraph_edges(node_ids)

    # ── Traverse Operations (delegated to GraphTraverser) ────────────

    async def traverse(
        self,
        start_entity: str,
        max_depth: int = 3,
        relation_types: list[str] | None = None,
        max_results: int = 100,
        timeout_seconds: int = 10,
        return_paths: bool = False,
        mode: str = "full",
        min_confidence: float | None = None,
    ) -> list[dict[str, Any]]:
        """Multi-hop graph traversal from a starting entity.

        Uses variable-length path matching to discover connected entities
        up to max_depth hops away, with optional filtering and aggregation.

        Args:
            start_entity: Canonical name of the starting entity.
            max_depth: Maximum traversal depth (1-6).
            relation_types: Optional list of relation types to filter.
            max_results: Maximum number of results.
            timeout_seconds: Timeout in seconds.
            return_paths: Whether to return complete paths.
            mode: Traversal mode - 'full' or 'aggregate'.
            min_confidence: Minimum confidence score filter.

        Returns:
            List of result dicts containing nodes, edges, and optionally paths/aggregate.
        """
        return await self._traverser.traverse(
            start_entity,
            max_depth=max_depth,
            relation_types=relation_types,
            max_results=max_results,
            timeout_seconds=timeout_seconds,
            return_paths=return_paths,
            mode=mode,
            min_confidence=min_confidence,
        )
