# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LadybugDB article repository for article graph operations.

LadybugDB-adapted version of Neo4jArticleRepo.
Uses id property instead of elementId(), and timestamp integers instead of datetime().
"""

from __future__ import annotations

import time
from typing import Any

from core.observability.logging import get_logger

log = get_logger("ladybug_article_repo")


class LadybugArticleRepo:
    """LadybugDB article repository.

    Handles article CRUD operations in LadybugDB graph database.

    Args:
        pool: LadybugPool instance.
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    async def create_article(
        self,
        pg_id: str,
        title: str,
        category: str,
        publish_time: int | None = None,
        score: float | None = None,
    ) -> str:
        """Create or update an article node.

        Args:
            pg_id: PostgreSQL article ID.
            title: Article title.
            category: Article category.
            publish_time: Publish timestamp (int, not datetime).
            score: Article score.

        Returns:
            The article ID.
        """
        import uuid

        article_id = str(uuid.uuid4())

        query = """
        MERGE (a:Article {pg_id: $pg_id})
        ON CREATE SET
            a.id = $id,
            a.title = $title,
            a.category = $category,
            a.publish_time = $publish_time,
            a.score = $score
        ON MATCH SET
            a.title = $title,
            a.category = $category,
            a.publish_time = $publish_time,
            a.score = $score
        RETURN a.id AS id
        """
        result = await self._pool.execute_query(
            query,
            {
                "pg_id": pg_id,
                "id": article_id,
                "title": title,
                "category": category,
                "publish_time": publish_time or 0,
                "score": score or 0.0,
            },
        )
        if result:
            return result[0]["id"]
        return article_id

    async def find_article_by_pg_id(self, pg_id: str) -> dict[str, Any] | None:
        """Find an article by its PostgreSQL ID."""
        query = """
        MATCH (a:Article {pg_id: $pg_id})
        RETURN a.id AS id,
               a.pg_id AS pg_id,
               a.title AS title,
               a.category AS category,
               a.publish_time AS publish_time,
               a.score AS score
        """
        result = await self._pool.execute_query(query, {"pg_id": pg_id})
        if result:
            return dict(result[0])
        return None

    async def find_article_by_id(self, article_id: str) -> dict[str, Any] | None:
        """Find an article by its ID."""
        query = """
        MATCH (a:Article {id: $id})
        RETURN a.id AS id,
               a.pg_id AS pg_id,
               a.title AS title,
               a.category AS category,
               a.publish_time AS publish_time,
               a.score AS score
        """
        result = await self._pool.execute_query(query, {"id": article_id})
        if result:
            return dict(result[0])
        return None

    async def create_followed_by_relation(
        self,
        from_pg_id: str,
        to_pg_id: str,
        time_gap_hours: float | None = None,
    ) -> None:
        """Create a FOLLOWED_BY relationship between two articles."""
        query = """
        MATCH (from:Article {pg_id: $from_pg_id})
        MATCH (to:Article {pg_id: $to_pg_id})
        MERGE (from)-[r:FOLLOWED_BY]->(to)
        SET r.time_gap_hours = $time_gap_hours
        """
        await self._pool.execute_query(
            query,
            {
                "from_pg_id": from_pg_id,
                "to_pg_id": to_pg_id,
                "time_gap_hours": time_gap_hours or 0.0,
            },
        )

    async def get_followed_articles(
        self,
        pg_id: str,
        direction: str = "outgoing",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get articles that follow or are followed by the given article."""
        if direction == "outgoing":
            query = """
            MATCH (a:Article {pg_id: $pg_id})-[r:FOLLOWED_BY]->(followed)
            RETURN followed.id AS id,
                   followed.pg_id AS pg_id,
                   followed.title AS title,
                   followed.category AS category,
                   r.time_gap_hours AS time_gap_hours
            LIMIT $limit
            """
        else:
            query = """
            MATCH (a:Article {pg_id: $pg_id})<-[r:FOLLOWED_BY]-(follower)
            RETURN follower.id AS id,
                   follower.pg_id AS pg_id,
                   follower.title AS title,
                   follower.category AS category,
                   r.time_gap_hours AS time_gap_hours
            LIMIT $limit
            """
        result = await self._pool.execute_query(query, {"pg_id": pg_id, "limit": limit})
        return [dict(r) for r in result]

    async def delete_article(self, pg_id: str) -> bool:
        """Delete an article and its relationships."""
        query = """
        MATCH (a:Article {pg_id: $pg_id})
        WITH a, COUNT(a) AS count
        DELETE a
        RETURN count
        """
        result = await self._pool.execute_query(query, {"pg_id": pg_id})
        return bool(result and result[0].get("count", 0) > 0)

    async def delete_old_articles(self, days: int = 90) -> int:
        """Delete articles older than specified days."""
        cutoff = int(time.time()) - (days * 24 * 60 * 60)
        # Find old articles
        query = """
        MATCH (a:Article)
        WHERE a.publish_time < $cutoff
        RETURN a.pg_id AS pg_id
        """
        result = await self._pool.execute_query(query, {"cutoff": cutoff})
        count = 0
        for r in result:
            await self.delete_article(r["pg_id"])
            count += 1
        return count

    async def get_article_entities(self, pg_id: str) -> list[dict[str, Any]]:
        """Get all entities mentioned by an article."""
        query = """
        MATCH (a:Article {pg_id: $pg_id})-[r:MENTIONS]->(e:Entity)
        RETURN e.id AS entity_id,
               e.canonical_name AS canonical_name,
               e.type AS type,
               r.role AS role
        """
        result = await self._pool.execute_query(query, {"pg_id": pg_id})
        return [dict(r) for r in result]

    async def update_article_score(self, pg_id: str, score: float) -> None:
        """Update an article's score."""
        query = """
        MATCH (a:Article {pg_id: $pg_id})
        SET a.score = $score
        """
        await self._pool.execute_query(query, {"pg_id": pg_id, "score": score})

    async def delete_orphan_articles(self, valid_pg_ids: list[str]) -> int:
        """Delete articles that don't exist in PostgreSQL."""
        # Find orphan articles
        query = """
        MATCH (a:Article)
        RETURN a.pg_id AS pg_id
        """
        result = await self._pool.execute_query(query)
        orphan_pg_ids = [r["pg_id"] for r in result if r["pg_id"] not in valid_pg_ids]
        count = 0
        for pg_id in orphan_pg_ids:
            await self.delete_article(pg_id)
            count += 1
        return count

    async def list_all_article_pg_ids(self) -> list[str]:
        """List all article PostgreSQL IDs."""
        query = """
        MATCH (a:Article)
        RETURN a.pg_id AS pg_id
        """
        result = await self._pool.execute_query(query)
        return [r["pg_id"] for r in result]

    async def delete_articles_without_mentions(self) -> int:
        """Delete articles that have no MENTIONS relationships."""
        query = """
        MATCH (a:Article)
        WHERE NOT (a)-[:MENTIONS]->()
        RETURN a.pg_id AS pg_id
        """
        result = await self._pool.execute_query(query)
        count = 0
        for r in result:
            await self.delete_article(r["pg_id"])
            count += 1
        return count

    async def count_articles_without_mentions(self) -> int:
        """Count articles without MENTIONS relationships."""
        query = """
        MATCH (a:Article)
        WHERE NOT (a)-[:MENTIONS]->()
        RETURN COUNT(a) AS count
        """
        result = await self._pool.execute_query(query)
        return result[0]["count"] if result else 0
