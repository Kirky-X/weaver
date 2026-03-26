# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Vector repository for pgvector operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text

from core.db.models import EntityVector, VectorType
from core.db.postgres import PostgresPool
from core.observability.logging import get_logger

log = get_logger("vector_repo")


@dataclass
class SimilarArticle:
    """Result from a similarity search."""

    article_id: str
    category: str | None
    similarity: float
    hybrid_score: float | None = None


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
            await session.execute(text("SET hnsw.ef_search = 200;"))

            for vec_type, embedding in [
                (VectorType.TITLE.value, title_embedding),
                (VectorType.CONTENT.value, content_embedding),
            ]:
                if embedding is None:
                    continue

                existing_id = await session.execute(
                    text("""
                        SELECT id FROM article_vectors
                        WHERE article_id = :article_id AND vector_type = :vector_type
                        """),
                    {"article_id": article_id, "vector_type": vec_type},
                )
                existing = existing_id.scalar_one_or_none()

                if existing:
                    await session.execute(
                        text("""
                            UPDATE article_vectors
                            SET embedding = :embedding, model_id = :model_id, updated_at = NOW()
                            WHERE article_id = :article_id AND vector_type = :vector_type
                            """),
                        {
                            "article_id": article_id,
                            "vector_type": vec_type,
                            "embedding": f"[{','.join(map(str, embedding))}]",
                            "model_id": model_id,
                        },
                    )
                else:
                    await session.execute(
                        text("""
                            INSERT INTO article_vectors (article_id, vector_type, embedding, model_id)
                            VALUES (:article_id, :vector_type, :embedding, :model_id)
                            """),
                        {
                            "article_id": article_id,
                            "vector_type": vec_type,
                            "embedding": f"[{','.join(map(str, embedding))}]",
                            "model_id": model_id,
                        },
                    )

            await session.commit()

    async def bulk_upsert_article_vectors(
        self,
        articles: list[tuple[uuid.UUID, list[float] | None, list[float] | None, str]],
        batch_size: int = 100,
    ) -> int:
        """Bulk upsert article vectors using INSERT ON CONFLICT.

        Uses PostgreSQL's ON CONFLICT for efficient batch upsert without N+1 queries.

        Args:
            articles: List of (article_id, title_embedding, content_embedding, model_id) tuples.
            batch_size: Number of vectors to insert per batch (default 100).

        Returns:
            Number of vectors inserted/updated.
        """
        if not articles:
            return 0

        # Flatten all vectors into a single list for batch insert
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
            await session.execute(text("SET hnsw.ef_search = 200;"))

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
                    params[f"embedding_{j}"] = f"[{','.join(map(str, vec['embedding']))}]"
                    params[f"model_id_{j}"] = vec["model_id"]

                # S608 false positive: values_clause contains only parameter placeholders
                # All actual values are passed via params dict to SQLAlchemy's execute()
                query = text(f"""
                    INSERT INTO article_vectors (article_id, vector_type, embedding, model_id)
                    VALUES {values_clause}
                    ON CONFLICT (article_id, vector_type)
                    DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        model_id = EXCLUDED.model_id,
                        updated_at = NOW()
                """)  # noqa: S608

                result = await session.execute(query, params)
                total_count += result.rowcount

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
                    1 - (av.embedding <=> cast(:embedding as vector)) as similarity
                FROM article_vectors av
                JOIN articles a ON a.id = av.article_id
                WHERE av.vector_type = 'content'
                  AND a.is_merged = FALSE
                  AND 1 - (av.embedding <=> cast(:embedding as vector)) > :threshold
                  AND (cast(:category as category_type) IS NULL OR a.category = cast(:category as category_type))
                  AND (cast(:model_id as text) IS NULL OR av.model_id = cast(:model_id as text))
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
            query = text("""
                SELECT a.id::text AS article_id,
                       COALESCE(a.title, '') AS title,
                       COALESCE(a.body, '') AS body
                FROM articles a
                WHERE a.id::text = ANY(:article_ids)
            """)
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
                        1 - (av.embedding <=> cast(:embedding as vector)) as similarity
                    FROM article_vectors av
                    JOIN articles a ON a.id = av.article_id
                    WHERE av.vector_type = 'content'
                      AND a.is_merged = FALSE
                      AND 1 - (av.embedding <=> cast(:embedding as vector)) > :threshold
                      AND (cast(:category as category_type) IS NULL OR a.category = cast(:category as category_type))
                      AND (cast(:model_id as text) IS NULL OR av.model_id = cast(:model_id as text))
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

    async def update_entity_vectors_by_temp_keys(self, name_to_uuid: dict[str, str]) -> int:
        """Update entity vector records by replacing temp keys with actual UUIDs.

        This method is called after Neo4j entity creation to update the neo4j_id
        field with the actual entity UUIDs.

        Args:
            name_to_uuid: Mapping from entity canonical name to entity UUID.

        Returns:
            Number of records updated.
        """
        if not name_to_uuid:
            return 0

        updated_count = 0
        async with self._pool.session() as session:
            for name, uuid in name_to_uuid.items():
                temp_key = f"temp:{name}"

                # Check if temp record exists
                result = await session.execute(
                    select(EntityVector).where(EntityVector.neo4j_id == temp_key)
                )
                existing = result.scalar_one_or_none()

                if existing:
                    # Check if UUID version already exists
                    uuid_result = await session.execute(
                        select(EntityVector).where(EntityVector.neo4j_id == uuid)
                    )
                    uuid_existing = uuid_result.scalar_one_or_none()

                    if uuid_existing:
                        # UUID exists, update embedding and delete temp
                        uuid_existing.embedding = existing.embedding
                        await session.execute(
                            select(EntityVector).where(EntityVector.id == existing.id)
                        )
                        from sqlalchemy import delete

                        await session.execute(
                            delete(EntityVector).where(EntityVector.id == existing.id)
                        )
                    else:
                        # Update temp key to UUID
                        existing.neo4j_id = uuid

                    updated_count += 1

            await session.commit()
        return updated_count

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

            vector_str = f"[{','.join(map(str, embedding))}]"

            query = text("""
                SELECT
                    neo4j_id,
                    1 - (embedding <=> cast(:embedding as vector)) as similarity
                FROM entity_vectors
                WHERE 1 - (embedding <=> cast(:embedding as vector)) > :threshold
                ORDER BY similarity DESC
                LIMIT :limit
            """)

            result = await session.execute(
                query,
                {
                    "embedding": vector_str,
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
            query = text("""
                DELETE FROM article_vectors
                WHERE article_id = ANY(:ids)
            """)
            result = await session.execute(query, {"ids": [str(aid) for aid in article_ids]})
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

        async with self._pool.session() as session:
            query = text("""
                DELETE FROM entity_vectors
                WHERE neo4j_id = ANY(:ids)
            """)
            result = await session.execute(query, {"ids": neo4j_ids})
            await session.commit()
            return result.rowcount
