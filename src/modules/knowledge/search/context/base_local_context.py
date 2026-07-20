# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Base local context builder using Template Method pattern.

Provides shared build flow for entity-neighborhood search context,
with database-specific hooks for Neo4j and LadybugDB.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from core.observability import get_logger
from modules.knowledge.search.context.builder import ContextBuilder, SearchContext

if TYPE_CHECKING:
    from core.protocols import GraphPool

log = get_logger(__name__)


class BaseLocalContextBuilder(ContextBuilder):
    """Base class for local context builders using Template Method pattern.

    Provides the shared build flow for entity-neighborhood search:
    1. Find query entities (or use provided entity_names)
    2. Get entity details
    3. Get related entities
    4. Get relationships
    5. Get related articles (with PostgreSQL enrichment)
    6. Assemble SearchContext

    Subclasses must implement database-specific query methods.

    Implements: ContextBuilder
    """

    def __init__(
        self,
        graph_pool: GraphPool,
        article_repo: Any = None,
        token_encoder: Any = None,
        default_max_tokens: int = 8000,
        max_entities: int = 20,
        max_relationships: int = 50,
        max_hops: int = 2,
    ) -> None:
        super().__init__(token_encoder, default_max_tokens)
        self._pool = graph_pool
        self._article_repo = article_repo
        self._max_entities = max_entities
        self._max_relationships = max_relationships
        self._max_hops = max_hops

    # ── Template Method: build ──────────────────────────────────────────

    async def build(
        self,
        query: str,
        max_tokens: int | None = None,
        entity_names: list[str] | None = None,
        relation_types: list[str] | None = None,
        **kwargs: Any,
    ) -> SearchContext:
        """Build local context for a query.

        Args:
            query: The search query.
            max_tokens: Maximum tokens for context.
            entity_names: Optional list of entity names to focus on.
            relation_types: Optional list of relation types to filter by.
            **kwargs: Additional parameters.

        Returns:
            SearchContext with local entity neighborhood.
        """
        context = self.create_context(query, max_tokens)

        if entity_names is None:
            entity_names = await self._find_query_entities(query)
        elif self._should_validate_entity_names():
            # Verify provided entity_names exist; fall back to search if not
            entities_check = await self._get_entities_with_details(entity_names)
            if not entities_check:
                log.info(
                    "entity_names_not_found_fallback",
                    provided=entity_names,
                    query=query,
                )
                entity_names = await self._find_query_entities(query)

        if not entity_names:
            return await self._handle_no_entities(context, query)

        entities = await self._get_entities_with_details(entity_names)
        if entities:
            entity_content = self.format_entities_section(entities)
            context.add_content(
                name="Relevant Entities",
                content=entity_content,
                priority=100,
                metadata={"entity_count": len(entities)},
            )

        related_entities = await self._get_related_entities(
            entity_names,
            relation_types=relation_types,
        )
        if related_entities:
            related_content = self.format_entities_section(
                related_entities, include_description=False
            )
            context.add_content(
                name="Related Entities",
                content=related_content,
                priority=80,
                metadata={"related_count": len(related_entities)},
            )

        relationships = await self._get_relationships(
            entity_names,
            relation_types=relation_types,
        )
        if relationships:
            rel_content = self.format_relationships_section(
                relationships,
                include_direction=self._include_relationship_direction(),
            )
            context.add_content(
                name="Relationships",
                content=rel_content,
                priority=90,
                metadata={"relationship_count": len(relationships)},
            )

        articles = await self._get_related_articles(entity_names)
        if articles:
            article_content = self.format_articles_section(articles)
            context.add_content(
                name="Source Articles",
                content=article_content,
                priority=70,
                metadata={"article_count": len(articles)},
            )

        context.metadata["total_entities"] = len(entities) + len(related_entities)
        context.metadata["total_relationships"] = len(relationships)
        if relation_types:
            context.metadata["filtered_relation_types"] = relation_types

        return context

    # ── Hook methods (override in subclasses) ───────────────────────────

    def _should_validate_entity_names(self) -> bool:
        """Whether to validate provided entity_names against the database.

        LadybugDB validates because entity names may not exist due to
        different data model. Neo4j skips validation for performance.
        """
        return False

    def _include_relationship_direction(self) -> bool:
        """Whether to include direction indicators in relationship section."""
        return False

    async def _handle_no_entities(
        self,
        context: SearchContext,
        query: str,
    ) -> SearchContext:
        """Handle the case when no entities are found.

        Default behavior: try relational DB text search as fallback
        (searches both title and body via ``ArticleRepo.search_by_text``).

        Cross-database divergence (intentional, see design.md §H1):
        - Neo4j ``LocalContextBuilder`` uses this default behavior directly.
        - LadybugDB ``LadybugLocalContextBuilder`` overrides to first try
          graph-based Article node search (``_get_related_articles_by_text``)
          with Python-side title filtering, then falls back to the relational
          DB search. The LadybugDB path matches title only; the Neo4j path
          matches title + body. The two backends are NOT semantically
          equivalent in the no-entities fallback path — this is accepted as
          a trade-off because the LadybugDB path exists primarily to exercise
          its Cypher dialect's Article node query. See H1 in
          ``specmark/changes/db-consistency-verify/design.md`` for details.
        """
        context.add_content(
            name="Search Note",
            content=f"No direct entity matches found for '{query}'. Attempting to find related content...",
            priority=0,
        )

        # Fallback: search articles in relational DB (DuckDB/PostgreSQL)
        articles = await self._search_articles_in_relational_db(query)
        if articles:
            article_content = self.format_articles_section(articles)
            context.add_content(
                name="Related Articles",
                content=article_content,
                priority=50,
                metadata={"article_count": len(articles)},
            )
        else:
            context.add_content(
                name="No Entities Found",
                content="No relevant entities or articles found for the query.",
                priority=0,
            )
        return context

    async def _search_articles_in_relational_db(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search articles in relational DB (DuckDB/PostgreSQL) by text.

        This is a fallback when graph-based search returns no results.
        Uses ArticleRepo.search_by_text if available.

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            List of article dicts.
        """
        repo = getattr(self, "_article_repo", None)
        if not repo or not query.strip():
            return []

        try:
            # Use search_by_text if available (added in ArticleRepo)
            if hasattr(repo, "search_by_text"):
                articles = await repo.search_by_text(query, limit=limit)
                if articles:
                    log.info(
                        "relational_text_search_found",
                        count=len(articles),
                        query=query,
                    )
                return articles
        except Exception as exc:
            log.warning(
                "relational_text_search_failed",
                error=str(exc),
                query=query,
            )
        return []

    # ── Abstract methods (must implement in subclasses) ─────────────────

    @abstractmethod
    async def _find_query_entities(self, query: str) -> list[str]:
        """Find entities mentioned in the query."""
        ...

    @abstractmethod
    async def _get_entities_with_details(
        self,
        entity_names: list[str],
    ) -> list[dict[str, Any]]:
        """Get detailed information for entities."""
        ...

    @abstractmethod
    async def _get_related_entities(
        self,
        entity_names: list[str],
        relation_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get entities related to the query entities."""
        ...

    @abstractmethod
    async def _get_relationships(
        self,
        entity_names: list[str],
        relation_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get relationships involving the query entities."""
        ...

    @abstractmethod
    async def _get_related_articles(
        self,
        entity_names: list[str],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get articles mentioning the query entities."""
        ...
