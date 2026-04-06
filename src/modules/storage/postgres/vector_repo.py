# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified vector repository using QueryBuilder pattern.

This repository provides database-agnostic vector similarity operations
through the QueryBuilder abstraction, supporting both PostgreSQL (pgvector)
and DuckDB backends.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, text

from core.db.models import EntityVector, VectorType
from core.db.query_builders import VectorQueryBuilder
from core.observability.logging import get_logger
from core.protocols import RelationalPool

log = get_logger("vector_repo")


@dataclass
class SimilarArticle:
    """Result from a similarity search."""

    article_id: str
    category: str | None
    similarity: float
    hybrid_score: float | None = None
    publish_time: datetime | None = None
    created_at: datetime | None = None


@dataclass
class SimilarEntity:
    """Result from an entity similarity search."""

    neo4j_id: str
    similarity: float


class VectorRepo:
    """Unified repository for vector embedding operations.

    Uses QueryBuilder pattern to provide database-agnostic vector
    similarity searches and embedding storage. Supports both PostgreSQL
    (pgvector) and DuckDB backends through dependency injection.

    Implements:
        - VectorRepository: Vector similarity search and embedding storage

    Implements:
        - VectorRepository: Vector similarity search and embedding storage

    Args:
        pool: Relational database connection pool (PostgreSQL or DuckDB).
        query_builder: Database-specific query builder for vector operations.
    """

    def __init__(
        self,
        pool: RelationalPool,
        query_builder: VectorQueryBuilder,
    ) -> None:
        self._pool = pool
        self._query_builder = query_builder

    async def upsert_article_vectors(
        self,
        article_id: uuid.UUID,
        title_embedding: list[float] | None,
        content_embedding: list[float] | None,
        model_id: str = "text-embedding-3-large",  # Default for backward compatibility; should use configured model
    ) -> None:
        """Upsert title and content vectors for an article.

        Args:
            article_id: Article UUID.
            title_embedding: Title vector (1024-dim).
            content_embedding: Content vector (1024-dim).
            model_id: Embedding model identifier (e.g., "qwen3-embedding:0.6b", "text-embedding-3-large").
                      IMPORTANT: In production, this should come from settings.llm.embedding_model
                      rather than using the default value.
        """
        async with self._pool.session() as session:
            # Initialize session with database-specific settings
            for stmt in self._query_builder.get_session_init_statements():
                await session.execute(text(stmt))

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
            # Initialize session with database-specific settings
            for stmt in self._query_builder.get_session_init_statements():
                await session.execute(text(stmt))

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
    ) -> list[SimilarArticle]:
        """Find similar articles using vector similarity.

        Args:
            embedding: Query embedding vector.
            category: Optional category filter.
            threshold: Minimum cosine similarity threshold.
            limit: Maximum number of results.
            model_id: Optional model_id filter for embedding homogeneity.

        Returns:
            List of SimilarArticle results with timestamps for temporal decay.
        """
        from core.db.query_builders import SimilarityQuery

        config = SimilarityQuery(
            threshold=threshold,
            limit=limit,
            filter_by_category=category is not None,
            filter_by_model_id=model_id is not None,
        )

        async with self._pool.session() as session:
            # Initialize session with database-specific settings
            for stmt in self._query_builder.get_session_init_statements():
                await session.execute(text(stmt))

            query = text(self._query_builder.build_find_similar_articles_query(config))

            formatted_emb = self._query_builder.format_embedding_param(embedding)

            # Build params dict with only non-None values
            params: dict[str, str | list[float]] = {"embedding": formatted_emb}
            if category is not None:
                params["category"] = category
            if model_id is not None:
                params["model_id"] = model_id

            result = await session.execute(query, params)

            return [
                SimilarArticle(
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
    ) -> list[SimilarArticle]:
        """Find similar articles using hybrid vector + keyword scoring.

        Args:
            embedding: Query embedding vector.
            query_tokens: List of query keywords for text overlap scoring.
            category: Optional category filter.
            min_score: Minimum hybrid score threshold.
            limit: Maximum number of results.
            model_id: Optional model_id filter.

        Returns:
            List of SimilarArticle results with hybrid_score set.
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

        # Fetch article bodies for keyword overlap scoring
        article_ids = [r.article_id for r in vector_results]
        async with self._pool.session() as session:
            array_expr = self._query_builder.build_array_contains_expression(
                "a.id::text", ":article_ids"
            )
            query = text(f"""
                SELECT a.id::text AS article_id,
                       COALESCE(a.title, '') AS title,
                       COALESCE(a.body, '') AS body
                FROM articles a
                WHERE {array_expr}
            """)  # noqa: S608
            result = await session.execute(query, {"article_ids": article_ids})

        article_texts = {row.article_id: f"{row.title} {row.body}".lower() for row in result}

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
                    SimilarArticle(
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
    ) -> dict[uuid.UUID, list[SimilarArticle]]:
        """Batch find similar articles for multiple embeddings.

        Uses a single database session with concurrent queries for efficiency.

        Args:
            queries: List of (query_id, embedding) tuples.
            category: Optional category filter.
            threshold: Minimum cosine similarity threshold.
            limit: Maximum results per query.
            model_id: Optional model_id filter.

        Returns:
            Dict mapping query_id to list of similar articles.
        """
        from core.db.query_builders import SimilarityQuery

        if not queries:
            return {}

        config = SimilarityQuery(
            threshold=threshold,
            limit=limit,
            filter_by_category=category is not None,
            filter_by_model_id=model_id is not None,
        )
        results: dict[uuid.UUID, list[SimilarArticle]] = {}

        async with self._pool.session() as session:
            # Initialize session with database-specific settings
            for stmt in self._query_builder.get_session_init_statements():
                await session.execute(text(stmt))

            for query_id, embedding in queries:
                query = text(self._query_builder.build_find_similar_articles_query(config))
                formatted_emb = self._query_builder.format_embedding_param(embedding)

                # Build params dict with only non-None values
                params: dict[str, str | list[float]] = {"embedding": formatted_emb}
                if category is not None:
                    params["category"] = category
                if model_id is not None:
                    params["model_id"] = model_id

                rows = await session.execute(query, params)

                results[query_id] = [
                    SimilarArticle(
                        article_id=row.article_id,
                        category=row.category,
                        similarity=row.similarity,
                    )
                    for row in rows
                ]

        return results

    async def upsert_entity_vectors(
        self,
        entities: list[tuple[str, list[float]]],
        use_temp_key: bool = False,
    ) -> None:
        """Upsert entity vectors by name.

        Args:
            entities: List of (entity_name, embedding) tuples.
            use_temp_key: If True, use "temp:{name}" as neo4j_id for temporary storage.
                          The actual UUID should be set later via update_entity_vectors_by_temp_keys.
        """
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

    async def upsert_entity_vector(self, neo4j_id: str, embedding: list[float]) -> None:
        """Upsert a single entity vector."""
        await self.upsert_entity_vectors([(neo4j_id, embedding)], use_temp_key=False)

    async def find_similar_entities(
        self,
        embedding: list[float],
        threshold: float = 0.85,
        limit: int = 5,
    ) -> list[SimilarEntity]:
        """Find similar entities using vector similarity.

        Args:
            embedding: Query embedding vector.
            threshold: Minimum cosine similarity threshold.
            limit: Maximum number of results.

        Returns:
            List of SimilarEntity results.
        """
        from core.db.query_builders import EntitySimilarityQuery

        config = EntitySimilarityQuery(threshold=threshold, limit=limit)

        async with self._pool.session() as session:
            # Initialize session with database-specific settings
            for stmt in self._query_builder.get_session_init_statements():
                await session.execute(text(stmt))

            query = text(self._query_builder.build_find_similar_entities_query(config))
            formatted_emb = self._query_builder.format_embedding_param(embedding)

            result = await session.execute(
                query,
                {"embedding": formatted_emb},
            )

            return [
                SimilarEntity(
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
            array_expr = self._query_builder.build_array_contains_expression("article_id", ":ids")
            query = text(f"DELETE FROM article_vectors WHERE {array_expr}")  # noqa: S608
            result = await session.execute(query, {"ids": [str(aid) for aid in article_ids]})
            await session.commit()
            return getattr(result, "rowcount", 0)

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

        async with self._pool.session() as session:
            array_expr = self._query_builder.build_array_contains_expression("neo4j_id", ":ids")
            query = text(f"DELETE FROM entity_vectors WHERE {array_expr}")  # noqa: S608
            result = await session.execute(query, {"ids": neo4j_ids})
            await session.commit()
            return getattr(result, "rowcount", 0)

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

        async with self._pool.session() as session:
            updated = 0
            for temp_key, neo4j_id in temp_key_to_neo4j.items():
                query = text("""
                    UPDATE entity_vectors
                    SET neo4j_id = :neo4j_id, updated_at = NOW()
                    WHERE neo4j_id = :temp_key
                """)
                result = await session.execute(
                    query,
                    {"temp_key": temp_key, "neo4j_id": neo4j_id},
                )
                updated += getattr(result, "rowcount", 0)
            await session.commit()
            return updated

    async def get_entity_vectors_with_temp_keys(self) -> list[tuple[str, list[float]]]:
        """Get entity vectors that still use temp keys (not real Neo4j IDs).

        Returns:
            List of (neo4j_id, embedding) tuples for vectors with temp keys.
        """
        async with self._pool.session() as session:
            query = text("""
                SELECT neo4j_id, embedding
                FROM entity_vectors
                WHERE neo4j_id LIKE 'temp_%'
            """)
            result = await session.execute(query)
            return [(row[0], row[1]) for row in result]

    async def count_entities_with_valid_neo4j_ids(self) -> int:
        """Count entity vectors that have valid (non-temp) Neo4j IDs.

        Returns:
            Number of entity vectors with real Neo4j IDs.
        """
        async with self._pool.session() as session:
            query = text("""
                SELECT COUNT(*)
                FROM entity_vectors
                WHERE neo4j_id NOT LIKE 'temp_%'
            """)
            result = await session.execute(query)
            return result.scalar() or 0
