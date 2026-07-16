# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Community vector repository for community similarity search.

This repository provides vector similarity operations for community vectors.
"""

from __future__ import annotations

from sqlalchemy import text

from core.db.query_builders import VectorQueryBuilder
from core.mappers.community_search_result_mapper import CommunitySearchResultMapper
from core.models.shared import CommunitySearchResultView
from core.observability import get_logger
from core.protocols import RelationalPool

log = get_logger(__name__)


class CommunityVectorRepo:
    """Repository for community vector similarity operations.

    Args:
        pool: Relational database connection pool.
        query_builder: Database-specific query builder for vector operations.
    """

    def __init__(
        self,
        pool: RelationalPool,
        query_builder: VectorQueryBuilder,
    ) -> None:
        self._pool = pool
        self._query_builder = query_builder

    async def find_similar_communities(
        self,
        embedding: list[float],
        limit: int = 5,
        threshold: float = 0.80,
    ) -> list[CommunitySearchResultView]:
        """Find similar communities using vector similarity.

        Args:
            embedding: Query embedding vector.
            limit: Maximum number of results.
            threshold: Minimum similarity threshold.

        Returns:
            List of CommunitySearchResultView with community_id, score, and title.
        """
        # Build query for community_vectors table
        # Uses HNSW index for fast approximate nearest neighbor search
        query_sql = """
            SELECT
                community_id,
                1 - (embedding <=> CAST(:embedding AS vector)) AS score,
                title,
                summary
            FROM community_vectors
            WHERE 1 - (embedding <=> CAST(:embedding AS vector)) > :threshold
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
        """

        formatted_emb = self._query_builder.format_embedding_param(embedding)

        async with self._pool.session() as session:
            # Set ef_search dynamically for PostgreSQL (global default for community search)
            if self._query_builder.database_type == DatabaseType.POSTGRES:
                await session.execute(text("SET hnsw.ef_search = 60"))

            result = await session.execute(
                text(query_sql),
                {
                    "embedding": formatted_emb,
                    "threshold": threshold,
                    "limit": limit,
                },
            )

            rows = result.all()

            return [
                CommunitySearchResultMapper().to_view(
                    {
                        "community_id": row.community_id,
                        "score": float(row.score),
                        "title": row.title,
                        "summary": row.summary,
                    }
                )
                for row in rows
            ]

    async def upsert_community_vector(
        self,
        community_id: str,
        embedding: list[float],
        title: str | None = None,
        summary: str | None = None,
        entity_count: int = 0,
        article_count: int = 0,
        rank: float | None = None,
        model_id: str = "text-embedding-3-large",
    ) -> None:
        """Insert or update a community vector in community_vectors table.

        Synchronizes community embeddings from Neo4j CommunityReport to
        PostgreSQL community_vectors for similarity search.

        Args:
            community_id: Community UUID string.
            embedding: Embedding vector (dimension must match column type).
            title: Community title (optional).
            summary: Community summary (optional).
            entity_count: Number of entities in community.
            article_count: Number of articles in community.
            rank: Community importance rank (0.0-10.0).
            model_id: Embedding model identifier.
        """
        formatted_emb = self._query_builder.format_embedding_param(embedding)

        # UPSERT via ON CONFLICT (community_id) — works for PostgreSQL.
        # DuckDB uses INSERT OR REPLACE but community_vectors is PG-only
        # (pgvector HNSW index). DuckDB fallback doesn't support this table.
        upsert_sql = """
            INSERT INTO community_vectors
                (community_id, embedding, model_id, title, summary,
                 entity_count, article_count, rank, updated_at)
            VALUES
                (:community_id, CAST(:embedding AS vector), :model_id, :title, :summary,
                 :entity_count, :article_count, :rank, NOW())
            ON CONFLICT (community_id) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                model_id = EXCLUDED.model_id,
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                entity_count = EXCLUDED.entity_count,
                article_count = EXCLUDED.article_count,
                rank = EXCLUDED.rank,
                updated_at = NOW()
        """

        async with self._pool.session() as session:
            await session.execute(
                text(upsert_sql),
                {
                    "community_id": community_id,
                    "embedding": formatted_emb,
                    "model_id": model_id,
                    "title": title,
                    "summary": summary,
                    "entity_count": entity_count,
                    "article_count": article_count,
                    "rank": rank,
                },
            )
            await session.commit()
