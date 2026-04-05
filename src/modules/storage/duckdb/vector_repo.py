# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Vector repository for DuckDB operations.

DuckDB-adapted version of the PostgreSQL VectorRepo.
Uses array_cosine_similarity() instead of pgvector <=> operator.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

from core.db.models import VectorType
from core.observability.logging import get_logger

log = get_logger("duckdb_vector_repo")


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


class DuckDBVectorRepo:
    """Repository for DuckDB vector operations.

    Uses DuckDB's array_cosine_similarity() for similarity search.
    DuckDB uses FLOAT[1024] arrays instead of pgvector's vector type.

    Args:
        pool: DuckDB connection pool (implements RelationalPool).
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    async def upsert_article_vectors(
        self,
        article_id: uuid.UUID,
        title_embedding: list[float] | None,
        content_embedding: list[float] | None,
        model_id: str = "text-embedding-3-large",
    ) -> None:
        """Upsert title and content vectors for an article."""
        async with self._pool.session() as session:
            for vec_type, embedding in [
                (VectorType.TITLE.value, title_embedding),
                (VectorType.CONTENT.value, content_embedding),
            ]:
                if embedding is None:
                    continue

                # DuckDB uses INSERT OR REPLACE for upsert
                await session.execute(
                    text("""
                        INSERT OR REPLACE INTO article_vectors (article_id, vector_type, embedding, model_id)
                        VALUES (:article_id, :vector_type, :embedding, :model_id)
                    """),
                    {
                        "article_id": str(article_id),
                        "vector_type": vec_type,
                        "embedding": embedding,
                        "model_id": model_id,
                    },
                )

            await session.commit()

    async def bulk_upsert_article_vectors(
        self,
        articles: list[tuple[uuid.UUID, list[float] | None, list[float] | None, str]],
        batch_size: int = 100,
    ) -> int:
        """Bulk upsert article vectors."""
        if not articles:
            return 0

        all_vectors: list[dict] = []
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
            for i in range(0, len(all_vectors), batch_size):
                batch = all_vectors[i : i + batch_size]

                for vec in batch:
                    await session.execute(
                        text("""
                            INSERT OR REPLACE INTO article_vectors (article_id, vector_type, embedding, model_id)
                            VALUES (:article_id, :vector_type, :embedding, :model_id)
                        """),
                        vec,
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
        """Find similar articles using DuckDB array_cosine_similarity."""
        async with self._pool.session() as session:
            # Cast embedding to FLOAT[1024] to match column type
            query = text("""
                SELECT
                    a.id::VARCHAR as article_id,
                    a.category,
                    array_cosine_similarity(av.embedding, CAST(:embedding AS FLOAT[1024])) as similarity,
                    a.publish_time,
                    a.created_at
                FROM article_vectors av
                JOIN articles a ON a.id = av.article_id
                WHERE av.vector_type = 'content'
                  AND a.is_merged = FALSE
                  AND array_cosine_similarity(av.embedding, CAST(:embedding AS FLOAT[1024])) > :threshold
                  AND (:category IS NULL OR a.category = :category)
                  AND (:model_id IS NULL OR av.model_id = :model_id)
                ORDER BY similarity DESC
                LIMIT :limit
            """)

            result = await session.execute(
                query,
                {
                    "embedding": embedding,
                    "threshold": threshold,
                    "category": category,
                    "model_id": model_id,
                    "limit": limit,
                },
            )

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
        """Find similar articles using hybrid vector + keyword scoring."""
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
            query = text("""
                SELECT a.id::VARCHAR AS article_id,
                       COALESCE(a.title, '') AS title,
                       COALESCE(a.body, '') AS body
                FROM articles a
                WHERE a.id::VARCHAR IN (SELECT unnest(:article_ids))
            """)
            result = await session.execute(query, {"article_ids": article_ids})

        article_texts = {row.article_id: f"{row.title} {row.body}".lower() for row in result}

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
        """Batch find similar articles for multiple embeddings."""
        if not queries:
            return {}

        results: dict[uuid.UUID, list[SimilarArticle]] = {}

        async with self._pool.session() as session:
            for query_id, embedding in queries:
                # Cast embedding to FLOAT[1024] to match column type
                query = text("""
                    SELECT
                        a.id::VARCHAR as article_id,
                        a.category,
                        array_cosine_similarity(av.embedding, CAST(:embedding AS FLOAT[1024])) as similarity
                    FROM article_vectors av
                    JOIN articles a ON a.id = av.article_id
                    WHERE av.vector_type = 'content'
                      AND a.is_merged = FALSE
                      AND array_cosine_similarity(av.embedding, CAST(:embedding AS FLOAT[1024])) > :threshold
                      AND (:category IS NULL OR a.category = :category)
                      AND (:model_id IS NULL OR av.model_id = :model_id)
                    ORDER BY similarity DESC
                    LIMIT :limit
                """)

                rows = await session.execute(
                    query,
                    {
                        "embedding": embedding,
                        "threshold": threshold,
                        "category": category,
                        "model_id": model_id,
                        "limit": limit,
                    },
                )

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
        """Upsert entity vectors by name using raw SQL (avoids pgvector type issues)."""
        async with self._pool.session() as session:
            for name, embedding in entities:
                key = f"temp:{name}" if use_temp_key else name
                # Convert embedding to list if it's a tuple (DuckDB returns tuples)
                emb_list = list(embedding) if not isinstance(embedding, list) else embedding
                # Use raw SQL to avoid pgvector Vector type processing issues
                # DuckDB doesn't support :: cast, use CAST() instead
                query = text("""
                    INSERT INTO entity_vectors (neo4j_id, embedding, model_id, updated_at)
                    VALUES (:neo4j_id, CAST(:embedding AS FLOAT[1024]), 'text-embedding-3-large', NOW())
                    ON CONFLICT (neo4j_id) DO UPDATE SET
                        embedding = excluded.embedding,
                        updated_at = NOW()
                """)
                await session.execute(
                    query,
                    {"neo4j_id": key, "embedding": emb_list},
                )
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
        """Find similar entities using DuckDB array_cosine_similarity."""
        async with self._pool.session() as session:
            # Cast embedding to FLOAT[1024] to match column type
            query = text("""
                SELECT
                    neo4j_id,
                    array_cosine_similarity(embedding, CAST(:embedding AS FLOAT[1024])) as similarity
                FROM entity_vectors
                WHERE array_cosine_similarity(embedding, CAST(:embedding AS FLOAT[1024])) > :threshold
                ORDER BY similarity DESC
                LIMIT :limit
            """)

            result = await session.execute(
                query,
                {
                    "embedding": embedding,
                    "threshold": threshold,
                    "limit": limit,
                },
            )

            return [
                SimilarEntity(
                    neo4j_id=row.neo4j_id,
                    similarity=row.similarity,
                )
                for row in result
            ]

    async def delete_article_vectors_by_article_ids(self, article_ids: list[uuid.UUID]) -> int:
        """Delete article vectors by article IDs."""
        if not article_ids:
            return 0

        async with self._pool.session() as session:
            query = text("""
                DELETE FROM article_vectors
                WHERE article_id IN (SELECT unnest(:ids))
            """)
            result = await session.execute(query, {"ids": [str(aid) for aid in article_ids]})
            await session.commit()
            return result.rowcount

    async def delete_entity_vectors_by_neo4j_ids(self, neo4j_ids: list[str]) -> int:
        """Delete entity vectors by Neo4j IDs."""
        if not neo4j_ids:
            return 0

        async with self._pool.session() as session:
            query = text("""
                DELETE FROM entity_vectors
                WHERE neo4j_id IN (SELECT unnest(:ids))
            """)
            result = await session.execute(query, {"ids": neo4j_ids})
            await session.commit()
            return result.rowcount

    async def update_entity_vectors_by_temp_keys(self, temp_key_to_neo4j: dict[str, str]) -> int:
        """Update entity vectors by replacing temp keys with real Neo4j IDs."""
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
                updated += result.rowcount
            await session.commit()
            return updated

    async def get_entity_vectors_with_temp_keys(self) -> list[tuple[str, list[float]]]:
        """Get entity vectors that still use temp keys."""
        async with self._pool.session() as session:
            query = text("""
                SELECT neo4j_id, embedding
                FROM entity_vectors
                WHERE neo4j_id LIKE 'temp_%'
            """)
            result = await session.execute(query)
            return [(row[0], row[1]) for row in result]

    async def count_entities_with_valid_neo4j_ids(self) -> int:
        """Count entity vectors that have valid (non-temp) Neo4j IDs."""
        async with self._pool.session() as session:
            query = text("""
                SELECT COUNT(*)
                FROM entity_vectors
                WHERE neo4j_id NOT LIKE 'temp_%'
            """)
            result = await session.execute(query)
            return result.scalar() or 0
