"""Vector repository for pgvector operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import ArticleVector, EntityVector, VectorType
from core.db.postgres import PostgresPool
from core.observability.logging import get_logger

log = get_logger("vector_repo")


@dataclass
class SimilarArticle:
    """Result from a similarity search."""

    article_id: str
    category: str | None
    similarity: float


@dataclass
class SimilarEntity:
    """Result from an entity similarity search."""

    neo4j_id: str
    similarity: float


class VectorRepo:
    """Repository for pgvector embedding operations.

    Handles HNSW-indexed similarity searches for both
    article and entity vectors.

    Args:
        pool: PostgreSQL connection pool.
    """

    def __init__(self, pool: PostgresPool) -> None:
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
            await session.execute(text("SET hnsw.ef_search = 200;"))

            for vec_type, embedding in [
                (VectorType.TITLE.value, title_embedding),
                (VectorType.CONTENT.value, content_embedding),
            ]:
                if embedding is None:
                    continue

                existing_id = await session.execute(
                    text(
                        """
                        SELECT id FROM article_vectors
                        WHERE article_id = :article_id AND vector_type = :vector_type
                        """
                    ),
                    {"article_id": article_id, "vector_type": vec_type},
                )
                existing = existing_id.scalar_one_or_none()

                if existing:
                    await session.execute(
                        text(
                            """
                            UPDATE article_vectors
                            SET embedding = :embedding, model_id = :model_id, updated_at = NOW()
                            WHERE article_id = :article_id AND vector_type = :vector_type
                            """
                        ),
                        {"article_id": article_id, "vector_type": vec_type, "embedding": f"[{','.join(map(str, embedding))}]", "model_id": model_id},
                    )
                else:
                    await session.execute(
                        text(
                            """
                            INSERT INTO article_vectors (article_id, vector_type, embedding, model_id)
                            VALUES (:article_id, :vector_type, :embedding, :model_id)
                            """
                        ),
                        {"article_id": article_id, "vector_type": vec_type, "embedding": f"[{','.join(map(str, embedding))}]", "model_id": model_id},
                    )

            await session.commit()

    async def bulk_upsert_article_vectors(
        self,
        articles: list[tuple[uuid.UUID, list[float] | None, list[float] | None, str]],
    ) -> int:
        """Bulk upsert article vectors.

        Args:
            articles: List of (article_id, title_embedding, content_embedding, model_id) tuples.

        Returns:
            Number of vectors inserted/updated.
        """
        if not articles:
            return 0

        count = 0
        async with self._pool.session() as session:
            await session.execute(text("SET hnsw.ef_search = 200;"))

            for article_id, title_emb, content_emb, model_id in articles:
                for vec_type, embedding in [
                    (VectorType.TITLE.value, title_emb),
                    (VectorType.CONTENT.value, content_emb),
                ]:
                    if embedding is None:
                        continue

                    existing = await session.execute(
                        text(
                            """
                            SELECT id FROM article_vectors
                            WHERE article_id = :article_id AND vector_type = :vector_type
                            """
                        ),
                        {"article_id": article_id, "vector_type": vec_type},
                    )
                    if existing.scalar_one_or_none():
                        await session.execute(
                            text(
                                """
                                UPDATE article_vectors
                                SET embedding = :embedding, model_id = :model_id, updated_at = NOW()
                                WHERE article_id = :article_id AND vector_type = :vector_type
                                """
                            ),
                            {
                                "article_id": article_id,
                                "vector_type": vec_type,
                                "embedding": f"[{','.join(map(str, embedding))}]",
                                "model_id": model_id,
                            },
                        )
                    else:
                        await session.execute(
                            text(
                                """
                                INSERT INTO article_vectors (article_id, vector_type, embedding, model_id)
                                VALUES (:article_id, :vector_type, :embedding, :model_id)
                                """
                            ),
                            {
                                "article_id": article_id,
                                "vector_type": vec_type,
                                "embedding": f"[{','.join(map(str, embedding))}]",
                                "model_id": model_id,
                            },
                        )
                    count += 1

            await session.commit()
        return count

    async def find_similar(
        self,
        embedding: list[float],
        category: str | None = None,
        threshold: float = 0.80,
        limit: int = 20,
        model_id: str | None = None,
    ) -> list[SimilarArticle]:
        """Find similar articles using pgvector cosine similarity.

        Args:
            embedding: Query embedding vector.
            category: Optional category filter.
            threshold: Minimum cosine similarity threshold.
            limit: Maximum number of results.
            model_id: Optional model_id filter for embedding homogeneity.

        Returns:
            List of SimilarArticle results.
        """
        async with self._pool.session() as session:
            await session.execute(text("SET hnsw.ef_search = 200;"))

            vector_str = "[" + ",".join(str(x) for x in embedding) + "]"

            query = text("""
                SELECT
                    a.id::text as article_id,
                    a.category,
                    1 - (av.embedding <=> :embedding::vector) as similarity
                FROM article_vectors av
                JOIN articles a ON a.id = av.article_id
                WHERE av.vector_type = 'content'
                  AND a.is_merged = FALSE
                  AND 1 - (av.embedding <=> :embedding::vector) > :threshold
                  AND (:category IS NULL OR a.category = :category)
                  AND (:model_id IS NULL OR av.model_id = :model_id)
                ORDER BY similarity DESC
                LIMIT :limit
            """)

            result = await session.execute(
                query,
                {
                    "embedding": vector_str,
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
                )
                for row in result
            ]

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
        if not queries:
            return {}

        results: dict[uuid.UUID, list[SimilarArticle]] = {}

        async with self._pool.session() as session:
            await session.execute(text("SET hnsw.ef_search = 200;"))

            for query_id, embedding in queries:
                vector_str = "[" + ",".join(str(x) for x in embedding) + "]"

                query = text("""
                    SELECT
                        a.id::text as article_id,
                        a.category,
                        1 - (av.embedding <=> :embedding::vector) as similarity
                    FROM article_vectors av
                    JOIN articles a ON a.id = av.article_id
                    WHERE av.vector_type = 'content'
                      AND a.is_merged = FALSE
                      AND 1 - (av.embedding <=> :embedding::vector) > :threshold
                      AND (:category IS NULL OR a.category = :category)
                      AND (:model_id IS NULL OR av.model_id = :model_id)
                    ORDER BY similarity DESC
                    LIMIT :limit
                """)

                rows = await session.execute(
                    query,
                    {
                        "embedding": vector_str,
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
        self, entities: list[tuple[str, list[float]]]
    ) -> None:
        """Upsert entity vectors by name.

        Args:
            entities: List of (entity_name, embedding) tuples.
        """
        async with self._pool.session() as session:
            for name, embedding in entities:
                result = await session.execute(
                    select(EntityVector).where(EntityVector.neo4j_id == name)
                )
                existing = result.scalar_one_or_none()

                if existing:
                    existing.embedding = embedding
                else:
                    ev = EntityVector(
                        neo4j_id=name,
                        embedding=embedding,
                    )
                    session.add(ev)

            await session.commit()

    async def upsert_entity_vector(
        self, neo4j_id: str, embedding: list[float]
    ) -> None:
        """Upsert a single entity vector."""
        await self.upsert_entity_vectors([(neo4j_id, embedding)])

    async def find_similar_entities(
        self,
        embedding: list[float],
        threshold: float = 0.85,
        limit: int = 5,
    ) -> list[SimilarEntity]:
        """Find similar entities using pgvector cosine similarity.

        Args:
            embedding: Query embedding vector.
            threshold: Minimum cosine similarity threshold.
            limit: Maximum number of results.

        Returns:
            List of SimilarEntity results.
        """
        async with self._pool.session() as session:
            await session.execute(text("SET hnsw.ef_search = 200;"))

            query = text("""
                SELECT
                    neo4j_id,
                    1 - (embedding <=> :embedding::vector) as similarity
                FROM entity_vectors
                WHERE 1 - (embedding <=> :embedding::vector) > :threshold
                ORDER BY similarity DESC
                LIMIT :limit
            """)

            result = await session.execute(
                query,
                {
                    "embedding": str(embedding),
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
            query = text("""
                DELETE FROM entity_vectors
                WHERE neo4j_id = ANY(:ids)
            """)
            result = await session.execute(query, {"ids": neo4j_ids})
            await session.commit()
            return result.rowcount
