# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Repository protocol definitions for data access abstraction.

This module defines Protocol classes that specify the expected interface
for various repositories. Using Protocol enables structural subtyping,
allowing any class that implements the required methods to satisfy the type.

All implementations MUST explicitly declare their protocol implementation
in their docstring using the "Implements:" section.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import uuid

    from core.protocols.types import (
        ArticleSearchResultView,
        ArticleTitleMeta,
        ArticleView,
        EntitySearchResultView,
        EntityView,
        PersistStatus,
        PipelineState,
    )


@runtime_checkable
class EntityRepository(Protocol):
    """Protocol for entity repository implementations.

    Any class implementing these methods can be used as an EntityRepository.

    Implementations:
        - Neo4jEntityRepo: Neo4j-based entity repository
        - LadybugEntityRepo: LadybugDB-based entity repository
    """

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

    async def find_entity_by_id(self, entity_id: str) -> EntityView | None:
        """Find an entity by its graph database internal ID.

        Args:
            entity_id: The graph database internal element ID (Neo4j elementId
                or LadybugDB id).

        Returns:
            EntityView if found, None otherwise.
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
    ) -> list[EntityView]:
        """Find multiple entities by names in a single query.

        Args:
            names: List of canonical names to search for.
            entity_type: The entity type to match.

        Returns:
            List of EntityView found.
        """
        ...


@runtime_checkable
class VectorRepository(Protocol):
    """Protocol for vector repository implementations.

    Any class implementing these methods can be used as a VectorRepository.

    Implementations:
        - VectorRepo: Unified vector repository with QueryBuilder pattern
    """

    async def find_similar(
        self,
        embedding: list[float],
        category: str | None = None,
        threshold: float = 0.80,
        limit: int = 20,
        model_id: str | None = None,
    ) -> list[ArticleSearchResultView]:
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
    ) -> list[EntitySearchResultView]:
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
        model_id: str,
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
        entity_id: str,
        embedding: list[float],
        model_id: str,
    ) -> None:
        """Upsert a single entity vector.

        Args:
            entity_id: Graph database entity ID (Neo4j elementId or LadybugDB id).
            embedding: Entity embedding vector.
            model_id: Embedding model identifier from configuration.
        """
        ...

    async def upsert_event_embedding(
        self,
        event: Any,
        model_id: str,
    ) -> bool:
        """Upsert event embedding for MAGMA memory system.

        Args:
            event: EventNode instance with embedding data.
            model_id: Embedding model identifier from configuration.

        Returns:
            True if upsert was successful.

        Note:
            This method is specific to the MAGMA dual-stream memory
            evolution system for event embedding indexing.
        """
        ...


@runtime_checkable
class ArticleRepository(Protocol):
    """Protocol for article repository implementations.

    Any class implementing these methods can be used as an ArticleRepository.

    Implementations:
        - ArticleRepo: PostgreSQL-based article repository
    """

    async def get_by_id(self, article_id: uuid.UUID) -> ArticleView | None:
        """Get an article by ID.

        Args:
            article_id: Article UUID.

        Returns:
            ArticleView if found, None otherwise.
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

    async def get_existing_titles(self, titles: set[str]) -> set[str]:
        """Check which titles already exist in the database.

        Safety-net dedup (Level 3) for when SimHash fingerprints are
        missing (Redis degradation, process restart). Uses exact match.

        Args:
            titles: Set of titles to check.

        Returns:
            Set of titles that already exist in the database.
        """
        ...

    async def get_existing_content_hashes(self, content_hashes: set[str]) -> set[str]:
        """Check which content hashes already exist in the database.

        Cross-source dedup (Level 2.5) for when the same content is
        republished across different sources (different URLs). Catches
        duplicates that URL dedup and title SimHash both miss —
        especially when title extraction fails (empty title).

        Args:
            content_hashes: Set of SHA-256 content hashes to check.

        Returns:
            Set of content hashes that already exist in the database.
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

    async def fetch_titles_by_pg_ids(
        self,
        pg_ids: list[str],
    ) -> dict[str, ArticleTitleMeta]:
        """Batch fetch article metadata by PostgreSQL IDs.

        Used by graph-query callers that, after the Article node slim-down
        (design.md §D2), can only read ``pg_id`` from the graph DB and must
        look up ``title`` / ``category`` / ``publish_time`` / ``score`` from
        the relational DB in a single batched query.

        .. warning::
            Do NOT call this method inside a per-article loop — that
            defeats the N+1 avoidance. Pass the full ``pg_ids`` list in
            one shot.

        Args:
            pg_ids: List of article UUID strings. Empty list short-circuits
                without opening a session. Invalid UUID strings are skipped
                with a warning log (not raised). Mapping keys are lowercase
                UUID strings — callers querying the result must use
                ``pg_id.lower()`` to look up entries.

        Returns:
            Mapping of ``pg_id`` (lowercase UUID string) -> ``ArticleTitleMeta``.
            Missing IDs are omitted from the result. ``publish_time`` /
            ``score`` may be ``None`` for terminal or legacy articles.
        """
        ...

    async def fetch_bodies_by_pg_ids(
        self,
        pg_ids: list[str],
    ) -> dict[str, str]:
        """Batch fetch article body content by PostgreSQL IDs.

        Used by ``ContextBuilder.fetch_article_bodies`` to replace the
        N+1 per-id ``repo.get`` loop with a single batched SELECT against
        ``article_bodies``. Pairs with ``fetch_titles_by_pg_ids`` to
        rebuild full article context after the Article node slim-down
        (design.md §D2).

        .. warning::
            Do NOT call this method inside a per-article loop — that
            defeats the N+1 avoidance. Pass the full ``pg_ids`` list in
            one shot.

        Args:
            pg_ids: List of article UUID strings. Empty list short-circuits
                without opening a session. Invalid UUID strings are skipped
                with a warning log (not raised). Mapping keys are lowercase
                UUID strings — callers querying the result must use
                ``pg_id.lower()`` to look up entries.

        Returns:
            Mapping of ``pg_id`` (lowercase UUID string) -> body text.
            Missing IDs are omitted from the result (not empty string).
        """
        ...


@runtime_checkable
class SourceAuthorityRepository(Protocol):
    """Protocol for source authority repository implementations.

    Implementations:
        - SourceAuthorityRepo: PostgreSQL-based source authority repository
    """

    async def get_or_create(self, host: str, auto_score: float | None = None) -> Any: ...

    async def get(self, host: str) -> Any: ...

    async def update_authority(
        self, host: str, authority: float, tier: int | None = None, needs_review: bool = False
    ) -> None: ...

    async def get_needs_review(self) -> list[Any]: ...

    async def list_all(self) -> list[Any]: ...

    async def update_auto_score(self, host: str, auto_score: float) -> None: ...


@runtime_checkable
class GraphArticleRepository(Protocol):
    """Protocol for graph article repository implementations.

    After the Article node slim-down (design.md §D2), the graph Article node
    stores only ``{pg_id, created_at}`` (Neo4j) / ``{id, pg_id}`` (LadybugDB).
    Business fields (title / category / publish_time / score) are no longer
    persisted on the node — callers that need them must batch-fetch from
    PostgreSQL via ``ArticleRepository.fetch_titles_by_pg_ids``.

    Implementations:
        - Neo4jArticleRepo: Neo4j-based graph article repository
        - LadybugArticleRepo: LadybugDB-based graph article repository
    """

    async def create_article(
        self,
        article_id: str,
    ) -> str:
        """Create an Article node in the graph database.

        After the slim-down, only ``pg_id`` is persisted (plus an audit
        ``created_at`` for Neo4j). Title / category / publish_time / score
        are no longer accepted — callers that need them must batch-fetch
        from PostgreSQL via ``ArticleRepository.fetch_titles_by_pg_ids``.

        Args:
            article_id: PostgreSQL UUID of the article.

        Returns:
            The graph database internal ID of the created article.
        """
        ...

    async def create_articles_batch(
        self,
        articles: list[dict[str, Any]],
    ) -> list[str]:
        """Create multiple Article nodes in batch.

        After the slim-down, only ``pg_id`` is read from each article
        dict; other keys (title/category/publish_time/score) are silently
        ignored.

        Args:
            articles: List of dicts; each must contain ``pg_id``. Other
                keys are ignored for backward compatibility with existing
                pipeline state dicts.

        Returns:
            List of graph database internal IDs.
        """
        ...

    async def create_followed_by_batch(
        self,
        relations: list[dict[str, Any]],
    ) -> int:
        """Create multiple FOLLOWED_BY relationships in batch.

        Args:
            relations: List of dicts with from_article_id, to_article_id, time_gap_hours.

        Returns:
            Number of relationships created.
        """
        ...

    async def find_article_by_id(self, article_id: str) -> dict[str, Any] | None:
        """Find an article node by article ID (pg_id).

        After the slim-down, returns only graph-internal id + ``pg_id``
        (plus ``created_at`` for Neo4j).
        """
        ...

    async def find_articles_by_pg_ids(
        self,
        pg_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Batch existence lookup for Article nodes by pg_id.

        P4 fix: replaces the per-pg_id ``find_article_by_id`` loop in
        ``Neo4jWriter._create_followed_relations`` to avoid N+1
        round-trips on the pipeline write hot path. Returns a mapping
        of ``pg_id -> article_dict`` for every pg_id that exists in
        the graph. Missing pg_ids are simply absent from the result
        (callers treat absence as "source missing" and skip the
        relation, matching the single-row behaviour).

        Args:
            pg_ids: List of PostgreSQL article IDs to look up.

        Returns:
            Dict mapping each *found* pg_id to its article dict (same
            shape as ``find_article_by_id``). Empty input returns an
            empty dict without hitting the database.
        """
        ...

    async def find_article_by_graph_id(self, graph_id: str) -> dict[str, Any] | None:
        """Find an article node by graph database internal ID.

        After the slim-down, returns only graph-internal id + ``pg_id``
        (plus ``created_at`` for Neo4j).
        """
        ...

    async def create_followed_by_relation(
        self, from_article_id: str, to_article_id: str, time_gap_hours: float | None = None
    ) -> None: ...

    async def get_followed_articles(
        self, article_id: str, direction: str = "outgoing", limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get articles that follow or are followed by the given article.

        After the slim-down, returns only graph-internal id + ``pg_id`` +
        ``time_gap_hours``. Callers needing title/category/publish_time
        must batch-fetch from PostgreSQL.
        """
        ...

    async def delete_article(self, article_id: str) -> int:
        """Delete an Article node by PostgreSQL ID.

        T051 LOW-1: return type unified to ``int`` (count of nodes
        actually deleted). Both Neo4j and LadybugDB implementations
        return the number of nodes actually deleted (0 if no match,
        1 if a node was deleted) — callers can distinguish the no-op
        case (rule 12: failures must be explicit).
        """
        ...

    async def delete_old_articles(self, cutoff_pg_ids: list[str]) -> int:
        """Delete Article nodes whose pg_id is in ``cutoff_pg_ids``.

        After the slim-down, the Article node no longer carries
        ``publish_time``, so the cutoff cannot be computed inside the
        graph. Callers (writers) must query PostgreSQL for
        ``publish_time < NOW() - INTERVAL '$days days'`` and pass the
        resulting pg_ids here. Empty list is a no-op (no DB call).

        Args:
            cutoff_pg_ids: List of pg_ids to delete.

        Returns:
            Number of articles deleted.
        """
        ...

    async def get_article_entities(self, article_id: str) -> list[dict[str, Any]]: ...

    async def delete_orphan_articles(self, valid_article_ids: list[str]) -> int: ...

    async def list_all_article_ids(self) -> list[str]: ...

    async def delete_articles_without_mentions(self) -> int: ...

    async def count_articles_without_mentions(self) -> int: ...


@runtime_checkable
class GraphWriter(Protocol):
    """Protocol for graph writer implementations.

    Implementations:
        - Neo4jWriter: Neo4j-based graph writer
        - LadybugWriter: LadybugDB-based graph writer
    """

    async def ensure_constraints(self) -> None: ...

    @property
    def done_status(self) -> PersistStatus:
        """Return the PersistStatus for completed graph writes.

        Returns LADYBUG_DONE or NEO4J_DONE based on the graph backend type.
        """
        ...

    async def write(self, state: PipelineState) -> list[str]: ...

    async def write_batch(
        self,
        states: list[Any],
        concurrency: int = 10,
    ) -> dict[str, Any]:
        """Write multiple pipeline states to graph database.

        Args:
            states: List of pipeline states to persist.
            concurrency: Maximum concurrent writes.

        Returns:
            Dict with graph_ids as list[list[str]] (per-article grouping),
            article_ids list, and errors list.
        """
        ...

    async def cleanup_orphan_entities(self) -> int: ...

    async def archive_old_articles(self, cutoff_pg_ids: list[str]) -> int:
        """Archive (delete) Article nodes whose pg_id is in ``cutoff_pg_ids``.

        After the Article node slim-down (design.md §D2), the graph node no
        longer carries ``publish_time``, so the cutoff must be computed by
        the caller (typically by querying PostgreSQL for
        ``publish_time < NOW() - INTERVAL '$days days'``) and the resulting
        pg_ids passed in here. The writer delegates to
        ``GraphArticleRepository.delete_old_articles``.

        Args:
            cutoff_pg_ids: List of pg_ids to delete. Empty list is a no-op.

        Returns:
            Number of articles deleted.
        """
        ...

    async def merge_narrative(
        self,
        article_id: str,
        source_bias: str,
        frame: str,
        tone: str,
        emphasis: str,
    ) -> str:
        """Merge a NarrativeNode and link it to the article's EventNode.

        Creates or updates a NarrativeNode with the four framing dimensions,
        then establishes EventNode-[:HAS_NARRATIVE]->NarrativeNode relationship
        (EventNode is matched by `id = article_id`, which LadybugWriter.write
        and Neo4jWriter.write already create during article persistence).

        Args:
            article_id: Article UUID string. Used to match the EventNode.
            source_bias: 媒体立场倾向（左倾/右倾/中立/官方/民营 等）.
            frame: 叙事框架（经济影响/技术突破/政策监管/社会影响 等）.
            tone: 文章语调（乐观/悲观/客观/批判/振奋 等）.
            emphasis: 报道侧重点（合作战略/市场竞争/风险警示/技术创新 等）.

        Returns:
            The graph database internal ID of the NarrativeNode.
        """
        ...

    async def merge_schema(
        self,
        event_type: str,
        pattern: str,
        confidence: float,
    ) -> str:
        """Merge a SchemaNode keyed by event_type (no relationships).

        Creates or updates a SchemaNode capturing the structural pattern of
        an event type. SchemaNode is MERGEd so that multiple articles
        with the same event_type produce a single SchemaNode (idempotent
        upsert). Neo4j MERGEs on ``event_type`` (backed by a UNIQUE
        constraint); LadybugDB MERGEs on the primary key ``id``
        (``schema-{event_type}``) because Kùzu requires the primary key
        in the MERGE pattern. No relationships are created (SchemaNode
        stands alone as a schema registry consumed by
        SchemaDrivenStructuredOutput).

        Args:
            event_type: Event type string (e.g. 融资/政策发布/人事变动).
            pattern: JSON Schema string describing the event's fields.
            confidence: LLM confidence score [0.0, 1.0].

        Returns:
            The SchemaNode business-level ID (format: "schema-{event_type}"),
            stable across re-runs and consistent across Neo4j/Ladybug backends.
        """
        ...


@runtime_checkable
class AnalyticsStorageProtocol(Protocol):
    """Protocol for analytics storage implementations.

    Implementations:
        - AnalyticsStorage: PostgreSQL/DuckDB-backed analytics storage
          (src/modules/analytics/storage.py)

    Used by:
        - BriefingGenerator (T004): depends on this Protocol for fetching
          articles + persisting daily briefings.
        - T008 DailyBriefingService: depends on this Protocol for fetching
          (get_briefing) + listing (list_briefings) existing briefings.
          Generation is delegated to BriefingGenerator (which itself uses
          fetch_articles_for_briefing + save_briefing on this same Protocol).
        - T010 scheduler: will use DailyBriefingService, transitively
          depends on this Protocol.

    Decoupling rationale: BriefingGenerator is in modules/briefing/, storage
    is in modules/analytics/. Protocol dependency avoids circular import
    and allows test mocks (test_generator.py uses AsyncMock satisfying
    this Protocol).

    Note: This Protocol declares the methods used by BriefingGenerator
    (fetch_articles_for_briefing, save_briefing) + DailyBriefingService
    (get_briefing, list_briefings). AnalyticsStorage also implements
    save_shift/get_shifts/get_briefings_with_items for other consumers
    (analytics endpoint, SentimentTrackerNode) — those legacy methods are
    not part of this Protocol.
    """

    async def fetch_articles_for_briefing(
        self,
        briefing_date: Any,
        category: str,
    ) -> list[dict[str, Any]]:
        """Fetch articles for a given date filtered by briefing category.

        Args:
            briefing_date: Date to fetch articles for.
            category: Briefing category (finance/tech/ai/general). Must be
                normalized by caller (None → 'general') before calling.

        Returns:
            List of article dicts with article_id/title/body/category/score/
            sentiment_score/credibility_score/quality_score/publish_time.
        """
        ...

    async def save_briefing(
        self,
        briefing_date: Any,
        category: str,
        summary: str | None,
        items: list[dict[str, Any]],
    ) -> int:
        """Persist a daily briefing + items.

        Idempotent: same (briefing_date, category) replaces existing briefing.

        Returns:
            The persisted briefing id.
        """
        ...

    async def get_briefing(
        self,
        briefing_date: Any,
        category: str,
    ) -> dict[str, Any] | None:
        """Fetch a single persisted briefing by (date, category).

        Args:
            briefing_date: Date to query.
            category: Briefing category (finance/tech/ai/general). Must be
                normalized by caller (None → 'general').

        Returns:
            Briefing dict with id/briefing_date/category/summary/items/
            generated_at, or None if not found. Items is a list of dicts
            with rank/article_id/category/score/reason.
        """
        ...

    async def list_briefings(
        self,
        date_from: Any,
        date_to: Any,
    ) -> list[dict[str, Any]]:
        """List briefings within a date range (inclusive).

        Args:
            date_from: Start date (inclusive).
            date_to: End date (inclusive).

        Returns:
            List of briefing dicts (same shape as get_briefing's return)
            ordered by briefing_date descending. Empty list if none in range.
        """
        ...
