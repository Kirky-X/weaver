# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LadybugDB article repository for article graph operations.

LadybugDB-adapted version of Neo4jArticleRepo.
Uses id property instead of elementId(), and timestamp integers instead of datetime().
"""

from __future__ import annotations

import time
from typing import Any

from core.observability.logging import get_logger

log = get_logger(__name__)


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

        # Check if article already exists
        existing = await self.find_article_by_pg_id(pg_id)
        if existing:
            # Update existing article
            query = """
            MATCH (a:Article {pg_id: $pg_id})
            SET a.title = $title,
                a.category = $category,
                a.publish_time = $publish_time,
                a.score = $score
            RETURN a.id AS id
            """
            result = await self._pool.execute_query(
                query,
                {
                    "pg_id": pg_id,
                    "title": title,
                    "category": category,
                    "publish_time": publish_time or 0,
                    "score": score or 0.0,
                },
            )
            if result:
                return result[0]["id"]
            return existing["id"]

        # Create new article — use CREATE since find_article_by_pg_id already
        # confirmed it doesn't exist. LadybugDB (Kuzu) requires the PRIMARY KEY
        # `id` to be provided at creation time.
        query = """
        CREATE (a:Article {
            id: $id,
            pg_id: $pg_id,
            title: $title,
            category: $category,
            publish_time: $publish_time,
            score: $score
        })
        RETURN a.id AS id
        """
        result = await self._pool.execute_query(
            query,
            {
                "id": article_id,
                "pg_id": pg_id,
                "title": title,
                "category": category,
                "publish_time": publish_time or 0,
                "score": score or 0.0,
            },
        )
        if result:
            return result[0]["id"]
        return article_id

    async def create_articles_batch(
        self,
        articles: list[dict[str, Any]],
    ) -> list[str]:
        """Create multiple Article nodes in batch.

        Note: LadybugDB requires PRIMARY KEY id at creation time.
        For existing articles, updates them individually.

        Args:
            articles: List of dicts with pg_id, title, category, publish_time, score.

        Returns:
            List of article IDs for created/updated articles.
        """
        if not articles:
            return []

        import uuid

        # LadybugDB doesn't support MERGE with ON CREATE/ON MATCH well
        # Process in batches: first check existing, then create/update
        existing_ids: dict[str, str] = {}
        to_create: list[dict[str, Any]] = []

        for article in articles:
            pg_id = article.get("pg_id")
            existing = await self.find_article_by_pg_id(pg_id)
            if existing:
                existing_ids[pg_id] = existing["id"]
            else:
                article["id"] = str(uuid.uuid4())
                to_create.append(article)

        # Batch create new articles
        created_ids: list[str] = []
        if to_create:
            query = """
            UNWIND $articles AS article
            CREATE (a:Article {
                id: article.id,
                pg_id: article.pg_id,
                title: article.title,
                category: article.category,
                publish_time: article.publish_time,
                score: article.score
            })
            RETURN a.id AS id
            """
            params = {"articles": to_create}
            result = await self._pool.execute_query(query, params)
            created_ids = [r["id"] for r in result if r.get("id")]

        # Update existing articles
        for pg_id, article_id in existing_ids.items():
            article = next((a for a in articles if a.get("pg_id") == pg_id), None)
            if article:
                query = """
                MATCH (a:Article {pg_id: $pg_id})
                SET a.title = $title,
                    a.category = $category,
                    a.publish_time = $publish_time,
                    a.score = $score
                """
                await self._pool.execute_query(
                    query,
                    {
                        "pg_id": pg_id,
                        "title": article.get("title", ""),
                        "category": article.get("category", "unknown"),
                        "publish_time": article.get("publish_time") or 0,
                        "score": article.get("score") or 0.0,
                    },
                )

        return created_ids + list(existing_ids.values())

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

    async def create_followed_by_batch(
        self,
        relations: list[dict[str, Any]],
    ) -> int:
        """Create multiple FOLLOWED_BY relationships in batch.

        Args:
            relations: List of dicts with from_pg_id, to_pg_id, time_gap_hours.

        Returns:
            Number of relationships created.
        """
        if not relations:
            return 0

        query = """
        UNWIND $relations AS rel
        MATCH (from:Article {pg_id: rel.from_pg_id})
        MATCH (to:Article {pg_id: rel.to_pg_id})
        MERGE (from)-[r:FOLLOWED_BY]->(to)
        SET r.time_gap_hours = rel.time_gap_hours
        RETURN count(r) AS created
        """
        params = {"relations": relations}
        result = await self._pool.execute_query(query, params)
        return result[0].get("created", 0) if result else 0

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
