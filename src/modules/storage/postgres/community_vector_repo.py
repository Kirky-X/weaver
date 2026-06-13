# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Community vector repository for community similarity search.

This repository provides vector similarity operations for community vectors,
used by DeepGraphRAGEngine for community filtering.
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

    Implements:
        CommunityVectorRepository: Community vector similarity search

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
                1 - (embedding <=> :embedding::vector) AS score,
                title,
                summary
            FROM community_vectors
            WHERE 1 - (embedding <=> :embedding::vector) > :threshold
            ORDER BY embedding <=> :embedding::vector
            LIMIT :limit
        """

        formatted_emb = self._query_builder.format_embedding_param(embedding)

        async with self._pool.session() as session:
            # Initialize session with database-specific settings
            for stmt in self._query_builder.get_session_init_statements():
                await session.execute(text(stmt))

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
