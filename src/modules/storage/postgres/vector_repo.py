# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified vector repository using QueryBuilder pattern.

This repository provides database-agnostic vector similarity operations
through the QueryBuilder abstraction, supporting both PostgreSQL (pgvector)
and DuckDB backends.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import String, delete, func, select, text, update

from core.db import Article, ArticleVector, EntityVector, VectorType
from core.db.query_builders import DatabaseType, VectorQueryBuilder
from core.models.shared import ArticleSearchResultView, EntitySearchResultView
from core.observability import get_logger
from core.protocols import RelationalPool

log = get_logger(__name__)


class VectorRepo:
    """Unified repository for vector embedding operations.

    Uses QueryBuilder pattern to provide database-agnostic vector
    similarity searches and embedding storage. Supports both PostgreSQL
    (pgvector) and DuckDB backends through dependency injection.

    Implements:
        VectorRepository: Vector similarity search and embedding storage

    Args:
        pool: Relational database connection pool (PostgreSQL or DuckDB).
        query_builder: Database-specific query builder for vector operations.
    """

    def __init__(
        self,
        pool: RelationalPool,
        query_builder: VectorQueryBuilder,
        ef_search_manager: Any = None,
    ) -> None:
        self._pool = pool
        self._query_builder = query_builder
        self._ef_search_manager = ef_search_manager

    async def upsert_article_vectors(
        self,
        article_id: uuid.UUID,
        title_embedding: list[float] | None,
        content_embedding: list[float] | None,
        model_id: str,
    ) -> None:
        """Upsert title and content vectors for an article.

        Args:
            article_id: Article UUID.
            title_embedding: Title vector (1024-dim).
            content_embedding: Content vector (1024-dim).
            model_id: Embedding model identifier from configuration.
        """
        async with self._pool.session() as session:
            # Write operations don't need ef_search setting
            for vec_type, embedding in [
                (VectorType.TITLE.value, title_embedding),
                (VectorType.CONTENT.value, content_embedding),
            ]:
                if embedding is None:
                    continue

                formatted_emb = self._query_builder.format_embedding_param(embedding)

                # Use QueryBuilder's upsert query
                query = text(self._query_builder.build_upsert_article_vector_query())
                await session.execute(
                    query,
                    {
                        "article_id": str(article_id),
                        "vector_type": vec_type,
                        "embedding": formatted_emb,
                        "model_id": model_id,
                    },
                )

            await session.commit()

    async def bulk_upsert_article_vectors(
        self,
        articles: list[tuple[uuid.UUID, list[float] | None, list[float] | None, str]],
        batch_size: int = 100,
    ) -> int:
        """Bulk upsert article vectors using database-specific batch strategy.

        For PostgreSQL: Uses ON CONFLICT for efficient batch upsert.
        For DuckDB: Uses individual INSERT OR REPLACE statements.

        Args:
            articles: List of (article_id, title_embedding, content_embedding, model_id) tuples.
            batch_size: Number of vectors to insert per batch (default 100).

        Returns:
            Number of vectors inserted/updated.
        """
        if not articles:
            return 0

        # Flatten all vectors into a single list for batch insert
        all_vectors: list[dict[str, Any]] = []
        for article_id, title_emb, content_emb, model_id in articles:
            if title_emb is not None:
                all_vectors.append(
                    {
                        "article_id": str(article_id),
                        "vector_type": VectorType.TITLE.value,
                        "embedding": title_emb,
                        "model_id": model_id,
                    }
                )
            if content_emb is not None:
                all_vectors.append(
                    {
                        "article_id": str(article_id),
                        "vector_type": VectorType.CONTENT.value,
                        "embedding": content_emb,
                        "model_id": model_id,
                    }
                )

        if not all_vectors:
            return 0

        total_count = 0
        async with self._pool.session() as session:
            # Write operations don't need ef_search setting

            # Try batch insert first (works for PostgreSQL)
            try:
                # Process in batches to avoid large single queries
                for i in range(0, len(all_vectors), batch_size):
                    batch = all_vectors[i : i + batch_size]

                    # Build VALUES clause with parameters
                    values_clause = ", ".join(
                        [
                            f"(:article_id_{j}, :vector_type_{j}, :embedding_{j}, :model_id_{j})"
                            for j in range(len(batch))
                        ]
                    )

                    params = {}
                    for j, vec in enumerate(batch):
                        params[f"article_id_{j}"] = vec["article_id"]
                        params[f"vector_type_{j}"] = vec["vector_type"]
                        params[f"embedding_{j}"] = self._query_builder.format_embedding_param(
                            vec["embedding"]
                        )
                        params[f"model_id_{j}"] = vec["model_id"]

                    # Build batch query using QueryBuilder
                    query = text(
                        self._query_builder.build_upsert_article_vector_batch_query(len(batch))
                    )

                    result = await session.execute(query, params)
                    total_count += getattr(result, "rowcount", 0)

            except NotImplementedError:
                # DuckDB doesn't support batch upsert, use individual inserts
                for vec in all_vectors:
                    query = text(self._query_builder.build_upsert_article_vector_query())
                    await session.execute(
                        query,
                        {
                            "article_id": vec["article_id"],
                            "vector_type": vec["vector_type"],
                            "embedding": self._query_builder.format_embedding_param(
                                vec["embedding"]
                            ),
                            "model_id": vec["model_id"],
                        },
                    )
                    total_count += 1

            await session.commit()

        return total_count

    async def find_similar(
        self,
        embedding: list[float],
        category: str | None = None,
        threshold: float = 0.80,
        limit: int = 20,
        model_id: str | None = None,
        vector_type: str = "content",
        search_mode: str | None = None,
    ) -> list[ArticleSearchResultView]:
        """Find similar articles using vector similarity.

        Args:
            embedding: Query embedding vector.
            category: Optional category filter.
            threshold: Minimum cosine similarity threshold.
            limit: Maximum number of results.
            model_id: Optional model_id filter for embedding homogeneity.
            vector_type: Vector type to filter (default "content").
            search_mode: Optional search mode for HNSW ef_search optimization.

        Returns:
            List of ArticleSearchResultView results with timestamps for temporal decay.
        """
        from core.db.query_builders import SimilarityQuery

        config = SimilarityQuery(
            threshold=threshold,
            limit=limit,
            vector_type=vector_type,
            filter_by_category=category is not None,
            filter_by_model_id=model_id is not None,
        )

        async with self._pool.session() as session:
            # Set ef_search dynamically in the SAME session as the query
            if self._query_builder.database_type == DatabaseType.POSTGRES:
                if self._ef_search_manager and search_mode:
                    ef_value = self._ef_search_manager.get_ef_search(search_mode)
                else:
                    ef_value = 100  # Default fallback
                # PostgreSQL SET command does not support parameter binding
                # (asyncpg converts :value to $1, but SET rejects placeholders).
                # ef_value originates from EfSearchManager.get_ef_search() (int)
                # or the hardcoded default 100 — int() cast guarantees safety.
                await session.execute(text(f"SET hnsw.ef_search = {int(ef_value)}"))
                log.debug("ef_search_set_in_session", ef_search=ef_value, mode=search_mode)

            query = text(self._query_builder.build_find_similar_articles_query(config))

            formatted_emb = self._query_builder.format_embedding_param(embedding)

            # Build params dict with required and optional values
            params: dict[str, str | list[float] | float] = {
                "embedding": formatted_emb,
                "threshold": threshold,
                "vector_type": vector_type,
            }
            if category is not None:
                params["category"] = category
            if model_id is not None:
                params["model_id"] = model_id

            result = await session.execute(query, params)

            return [
                ArticleSearchResultView(
                    article_id=row.article_id,
                    category=row.category,
                    similarity=row.similarity,
                    publish_time=row.publish_time,
                    created_at=row.created_at,
                )
                for row in result
            ]

    async def find_similar_hybrid(
        self,
        embedding: list[float],
        query_tokens: list[str],
        category: str | None = None,
        min_score: float = 0.0,
        limit: int = 20,
        model_id: str | None = None,
    ) -> list[ArticleSearchResultView]:
        """Find similar articles using hybrid vector + keyword scoring.

        Args:
            embedding: Query embedding vector.
            query_tokens: List of query keywords for text overlap scoring.
            category: Optional category filter.
            min_score: Minimum hybrid score threshold.
            limit: Maximum number of results.
            model_id: Optional model_id filter.

        Returns:
            List of ArticleSearchResultView results with hybrid_score set.
        """
        vector_results = await self.find_similar(
            embedding=embedding,
            category=category,
            threshold=0.0,
            limit=limit,
            model_id=model_id,
        )

        if not vector_results:
            return []

        # Fetch article bodies for keyword overlap scoring using ORM
        # Use string comparison for article_ids to handle both UUID and non-UUID formats
        article_id_strings = [r.article_id for r in vector_results]
        async with self._pool.session() as session:
            result = await session.execute(
                select(Article.id, Article.title, Article.body).where(
                    func.cast(Article.id, String).in_(article_id_strings)
                )
            )
            rows = result.all()

        article_texts = {str(row.id): f"{row.title or ''} {row.body or ''}".lower() for row in rows}

        # Calculate hybrid scores
        scored = []
        for r in vector_results:
            text_content = article_texts.get(r.article_id, "")
            if query_tokens and text_content:
                overlap = sum(1 for tok in query_tokens if tok.lower() in text_content)
                keyword_score = min(overlap / max(len(query_tokens), 1), 1.0)
            else:
                keyword_score = 0.0

            hybrid = 0.7 * r.similarity + 0.3 * keyword_score
            if hybrid >= min_score:
                scored.append(
                    ArticleSearchResultView(
                        article_id=r.article_id,
                        category=r.category,
                        similarity=r.similarity,
                        hybrid_score=hybrid,
                    )
                )

        scored.sort(key=lambda x: x.hybrid_score or 0, reverse=True)
        return scored[:limit]

    async def batch_find_similar(
        self,
        queries: list[tuple[uuid.UUID, list[float]]],
        category: str | None = None,
        threshold: float = 0.80,
        limit: int = 20,
        model_id: str | None = None,
        vector_type: str = "content",
    ) -> dict[uuid.UUID, list[ArticleSearchResultView]]:
        """Batch find similar articles for multiple embeddings.

        Uses a single database session with concurrent queries for efficiency.

        Args:
            queries: List of (query_id, embedding) tuples.
            category: Optional category filter.
            threshold: Minimum cosine similarity threshold.
            limit: Maximum results per query.
            model_id: Optional model_id filter.
            vector_type: Vector type to filter (default "content").

        Returns:
            Dict mapping query_id to list of similar articles.
        """
        from core.db.query_builders import SimilarityQuery

        if not queries:
            return {}

        config = SimilarityQuery(
            threshold=threshold,
            limit=limit,
            vector_type=vector_type,
            filter_by_category=category is not None,
            filter_by_model_id=model_id is not None,
        )

        if self._query_builder.database_type == DatabaseType.DUCKDB:
            return await self._batch_find_similar_duckdb(
                queries, config, category, threshold, limit, model_id, vector_type
            )

        results: dict[uuid.UUID, list[ArticleSearchResultView]] = {}

        async with self._pool.session() as session:
            # Set ef_search dynamically for PostgreSQL
            await session.execute(text("SET hnsw.ef_search = 100"))

            # Build query configurations for parallel execution
            async def execute_single_query(
                qid: uuid.UUID, embedding: list[float]
            ) -> tuple[uuid.UUID, list[ArticleSearchResultView]]:
                query = text(self._query_builder.build_find_similar_articles_query(config))
                formatted_emb = self._query_builder.format_embedding_param(embedding)

                # Build params dict with required and optional values
                params: dict[str, str | list[float] | float] = {
                    "embedding": formatted_emb,
                    "threshold": threshold,
                    "vector_type": vector_type,
                }
                if category is not None:
                    params["category"] = category
                if model_id is not None:
                    params["model_id"] = model_id

                rows = await session.execute(query, params)
                return (
                    qid,
                    [
                        ArticleSearchResultView(
                            article_id=row.article_id,
                            category=row.category,
                            similarity=row.similarity,
                        )
                        for row in rows
                    ],
                )

            # Execute all queries in parallel using asyncio.gather
            query_tasks = [
                execute_single_query(query_id, embedding) for query_id, embedding in queries
            ]
            query_results = await asyncio.gather(*query_tasks)

            # Build results dict from parallel execution results
            for qid, articles in query_results:
                results[qid] = articles

        return results

    async def _batch_find_similar_duckdb(
        self,
        queries: list[tuple[uuid.UUID, list[float]]],
        config: SimilarityQuery,
        category: str | None,
        threshold: float,
        limit: int,
        model_id: str | None,
        vector_type: str,
    ) -> dict[uuid.UUID, list[ArticleSearchResultView]]:
        """Batch find similar with DuckDB retry for single-writer conflicts.

        DuckDB sessions are NOT thread-safe, so queries must run sequentially
        (no asyncio.gather) on a single session.
        """
        max_retries = 3
        base_delay = 0.2
        for attempt in range(max_retries):
            try:
                results: dict[uuid.UUID, list[ArticleSearchResultView]] = {}
                async with self._pool.session() as session:
                    for query_id, embedding in queries:
                        query = text(self._query_builder.build_find_similar_articles_query(config))
                        formatted_emb = self._query_builder.format_embedding_param(embedding)
                        params: dict[str, str | list[float] | float] = {
                            "embedding": formatted_emb,
                            "threshold": threshold,
                            "vector_type": vector_type,
                        }
                        if category is not None:
                            params["category"] = category
                        if model_id is not None:
                            params["model_id"] = model_id
                        rows = await session.execute(query, params)
                        results[query_id] = [
                            ArticleSearchResultView(
                                article_id=row.article_id,
                                category=row.category,
                                similarity=row.similarity,
                            )
                            for row in rows
                        ]
                return results
            except Exception as exc:
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    log.debug(
                        "duckdb_batch_find_similar_retry",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay=delay,
                        error=str(exc)[:100],
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

    async def upsert_entity_vectors(
        self,
        entities: list[tuple[str, list[float]]],
        model_id: str,
        use_temp_key: bool = False,
    ) -> None:
        """Upsert entity vectors by name.

        Args:
            entities: List of (entity_name, embedding) tuples.
            use_temp_key: If True, use "temp:{name}" as neo4j_id for temporary storage.
                          The actual UUID should be set later via update_entity_vectors_by_temp_keys.
            model_id: Embedding model identifier.
        """
        # Check if using DuckDB (use query_builder approach)
        if self._query_builder.database_type == DatabaseType.DUCKDB:
            await self._upsert_entity_vectors_duckdb(entities, model_id, use_temp_key)
        else:
            # PostgreSQL: use ORM approach
            async with self._pool.session() as session:
                for name, embedding in entities:
                    # Use temp key for deferred UUID assignment
                    key = f"temp:{name}" if use_temp_key else name
                    result = await session.execute(
                        select(EntityVector).where(EntityVector.neo4j_id == key)
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        existing.embedding = embedding
                    else:
                        ev = EntityVector(
                            neo4j_id=key,
                            embedding=embedding,
                        )
                        session.add(ev)

                await session.commit()

    async def _upsert_entity_vectors_duckdb(
        self,
        entities: list[tuple[str, list[float]]],
        model_id: str,
        use_temp_key: bool,
    ) -> None:
        """Upsert entity vectors with DuckDB retry for single-writer conflicts."""
        max_retries = 3
        base_delay = 0.1
        for attempt in range(max_retries):
            try:
                async with self._pool.session() as session:
                    for name, embedding in entities:
                        key = f"temp:{name}" if use_temp_key else name
                        formatted_emb = self._query_builder.format_embedding_param(embedding)
                        query = text(self._query_builder.build_upsert_entity_vector_query())
                        await session.execute(
                            query,
                            {
                                "neo4j_id": key,
                                "embedding": formatted_emb,
                                "model_id": model_id,
                            },
                        )
                    await session.commit()
                return
            except Exception as exc:
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    log.debug(
                        "duckdb_upsert_entity_retry",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay=delay,
                        error=str(exc)[:100],
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

    async def upsert_entity_vector(
        self, neo4j_id: str, embedding: list[float], model_id: str
    ) -> None:
        """Upsert a single entity vector.

        Args:
            neo4j_id: Neo4j entity ID.
            embedding: Entity embedding vector.
            model_id: Embedding model identifier from configuration.
        """
        await self.upsert_entity_vectors(
            [(neo4j_id, embedding)], model_id=model_id, use_temp_key=False
        )

    async def upsert_event_embedding(self, event: object, model_id: str) -> bool:
        """Upsert event embedding for MAGMA memory system.

        Stores event embedding in article_vectors using the event's article UUID.
        Implements: VectorRepository.upsert_event_embedding

        Args:
            event: EventNode instance with id (str/UUID), embedding (list[float]).
            model_id: Embedding model identifier from configuration.

        Returns:
            True if upsert was successful.
        """
        import uuid as _uuid

        from modules.memory.core.event_node import EventNode

        if not isinstance(event, EventNode):
            log.warning("upsert_event_invalid_type", type=type(event).__name__)
            return False

        if not event.embedding:
            log.debug("upsert_event_no_embedding", event_id=event.id)
            return False

        try:
            article_id = _uuid.UUID(event.id)
        except (ValueError, AttributeError):
            log.warning("upsert_event_invalid_id", event_id=getattr(event, "id", None))
            return False

        await self.upsert_article_vectors(
            article_id=article_id,
            title_embedding=None,
            content_embedding=event.embedding,
            model_id=model_id,
        )
        log.debug("upsert_event_embedding_stored", event_id=event.id)
        return True

    async def find_similar_entities(
        self,
        embedding: list[float],
        threshold: float = 0.85,
        limit: int = 5,
    ) -> list[EntitySearchResultView]:
        """Find similar entities using vector similarity.

        Args:
            embedding: Query embedding vector.
            threshold: Minimum cosine similarity threshold.
            limit: Maximum number of results.

        Returns:
            List of EntitySearchResultView results.
        """
        from core.db.query_builders import EntitySimilarityQuery

        config = EntitySimilarityQuery(threshold=threshold, limit=limit)

        async with self._pool.session() as session:
            # Set ef_search dynamically for PostgreSQL
            if self._query_builder.database_type == DatabaseType.POSTGRES:
                await session.execute(text("SET hnsw.ef_search = 100"))

            query = text(self._query_builder.build_find_similar_entities_query(config))
            formatted_emb = self._query_builder.format_embedding_param(embedding)

            result = await session.execute(
                query,
                {"embedding": formatted_emb},
            )

            return [
                EntitySearchResultView(
                    neo4j_id=row.neo4j_id,
                    similarity=row.similarity,
                )
                for row in result
            ]

    async def delete_article_vectors_by_article_ids(self, article_ids: list[uuid.UUID]) -> int:
        """Delete article vectors by article IDs.

        Used to clean up orphan article vectors during Saga compensation
        when PostgreSQL persistence fails after vectors were already written.

        Args:
            article_ids: List of article UUIDs whose vectors should be deleted.

        Returns:
            Number of vectors deleted.
        """
        if not article_ids:
            return 0

        async with self._pool.session() as session:
            result = await session.execute(
                delete(ArticleVector).where(ArticleVector.article_id.in_(article_ids))
            )
            await session.commit()
            return result.rowcount

    async def delete_entity_vectors_by_neo4j_ids(self, neo4j_ids: list[str]) -> int:
        """Delete entity vectors by Neo4j IDs.

        Used to clean up orphan entity vectors after Neo4j cleanup.

        Args:
            neo4j_ids: List of Neo4j entity IDs to delete.

        Returns:
            Number of vectors deleted.
        """
        if not neo4j_ids:
            return 0

        if self._query_builder.database_type == DatabaseType.DUCKDB:
            return await self._delete_entity_vectors_duckdb(neo4j_ids)

        async with self._pool.session() as session:
            result = await session.execute(
                delete(EntityVector).where(EntityVector.neo4j_id.in_(neo4j_ids))
            )
            await session.commit()
            return result.rowcount

    async def _delete_entity_vectors_duckdb(self, neo4j_ids: list[str]) -> int:
        """Delete entity vectors with DuckDB retry for single-writer conflicts."""
        max_retries = 3
        base_delay = 0.1
        for attempt in range(max_retries):
            try:
                async with self._pool.session() as session:
                    result = await session.execute(
                        delete(EntityVector).where(EntityVector.neo4j_id.in_(neo4j_ids))
                    )
                    await session.commit()
                    return result.rowcount
            except Exception as exc:
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    log.debug(
                        "duckdb_delete_entity_retry",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay=delay,
                        error=str(exc)[:100],
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

    async def update_entity_vectors_by_temp_keys(self, temp_key_to_neo4j: dict[str, str]) -> int:
        """Update entity vectors by replacing temp keys with real Neo4j IDs.

        Used after Neo4j sync to update entity_vectors with real neo4j_ids
        instead of temporary UUIDs that were assigned during extraction.

        Args:
            temp_key_to_neo4j: Mapping from temp keys (UUIDs) to real Neo4j IDs.

        Returns:
            Number of vectors updated.
        """
        if not temp_key_to_neo4j:
            return 0

        from datetime import UTC, datetime

        async with self._pool.session() as session:
            updated = 0
            for temp_key, neo4j_id in temp_key_to_neo4j.items():
                result = await session.execute(
                    update(EntityVector)
                    .where(EntityVector.neo4j_id == temp_key)
                    .values(neo4j_id=neo4j_id, updated_at=datetime.now(UTC))
                )
                updated += result.rowcount
            await session.commit()
            return updated

    async def get_entity_vectors_with_temp_keys(self) -> list[tuple[str, list[float]]]:
        """Get entity vectors that still use temp keys (not real Neo4j IDs).

        Returns:
            List of (neo4j_id, embedding) tuples for vectors with temp keys.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(EntityVector.neo4j_id, EntityVector.embedding).where(
                    EntityVector.neo4j_id.like("temp_%")
                )
            )
            return [(row.neo4j_id, row.embedding) for row in result]

    async def count_entities_with_valid_neo4j_ids(self) -> int:
        """Count entity vectors that have valid (non-temp) Neo4j IDs.

        Returns:
            Number of entity vectors with real Neo4j IDs.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(func.count())
                .select_from(EntityVector)
                .where(EntityVector.neo4j_id.not_like("temp_%"))
            )
            return result.scalar() or 0
