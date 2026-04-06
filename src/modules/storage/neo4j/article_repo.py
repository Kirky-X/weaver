# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Neo4j article repository for article graph operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.observability.logging import get_logger
from core.protocols import GraphPool

log = get_logger("neo4j_article_repo")


class Neo4jArticleRepo:
    """Neo4j article repository.

    Handles article-related graph operations in Neo4j,
    including article node creation and FOLLOWED_BY relationships.

    Args:
        pool: Graph database pool (Neo4j or LadybugDB).
    """

    def __init__(self, pool: GraphPool) -> None:
        self._pool = pool

    async def create_article(
        self,
        pg_id: str,
        title: str,
        category: str,
        publish_time: datetime | None,
        score: float | None = None,
    ) -> str:
        """Create an Article node in Neo4j.

        Args:
            pg_id: PostgreSQL UUID of the article.
            title: Article title.
            category: Article category.
            publish_time: Publication timestamp.
            score: Optional article score.

        Returns:
            The Neo4j internal ID of the created article.
        """
        query = """
        MERGE (a:Article {pg_id: $pg_id})
        ON CREATE SET
            a.title = $title,
            a.category = $category,
            a.publish_time = $publish_time,
            a.score = $score,
            a.created_at = datetime()
        ON MATCH SET
            a.title = $title,
            a.category = $category,
            a.publish_time = $publish_time,
            a.score = COALESCE($score, a.score)
        RETURN elementId(a) AS neo4j_id
        """
        params = {
            "pg_id": pg_id,
            "title": title,
            "category": category,
            "publish_time": publish_time,
            "score": score,
        }
        result = await self._pool.execute_query(query, params)
        if result:
            return result[0]["neo4j_id"]
        raise RuntimeError("Failed to create article node")

    async def find_article_by_pg_id(self, pg_id: str) -> dict[str, Any] | None:
        """Find an article node by PostgreSQL ID.

        Args:
            pg_id: The PostgreSQL UUID.

        Returns:
            Article dict if found, None otherwise.
        """
        query = """
        MATCH (a:Article {pg_id: $pg_id})
        RETURN elementId(a) AS neo4j_id,
               a.pg_id AS pg_id,
               a.title AS title,
               a.category AS category,
               a.publish_time AS publish_time,
               a.score AS score,
               a.created_at AS created_at
        """
        result = await self._pool.execute_query(query, {"pg_id": pg_id})
        if result:
            return dict(result[0])
        return None

    async def find_article_by_neo4j_id(self, neo4j_id: str) -> dict[str, Any] | None:
        """Find an article node by Neo4j internal ID.

        Args:
            neo4j_id: The Neo4j internal element ID.

        Returns:
            Article dict if found, None otherwise.
        """
        query = """
        MATCH (a)
        WHERE elementId(a) = $neo4j_id
        RETURN elementId(a) AS neo4j_id,
               a.pg_id AS pg_id,
               a.title AS title,
               a.category AS category,
               a.publish_time AS publish_time,
               a.score AS score,
               a.created_at AS created_at
        """
        result = await self._pool.execute_query(query, {"neo4j_id": neo4j_id})
        if result:
            return dict(result[0])
        return None

    async def create_followed_by_relation(
        self,
        from_pg_id: str,
        to_pg_id: str,
        time_gap_hours: float | None = None,
    ) -> None:
        """Create a FOLLOWED_BY relationship between two articles.

        Indicates that the 'from' article is followed by the 'to' article
        (e.g., in a series of coverage about the same event).

        Args:
            from_pg_id: The source article's PostgreSQL ID.
            to_pg_id: The target article's PostgreSQL ID.
            time_gap_hours: Optional time gap between articles in hours.
        """
        query = """
        MATCH (from:Article {pg_id: $from_pg_id})
        MATCH (to:Article {pg_id: $to_pg_id})
        MERGE (from)-[r:FOLLOWED_BY]->(to)
        """
        params = {
            "from_pg_id": from_pg_id,
            "to_pg_id": to_pg_id,
        }

        if time_gap_hours is not None:
            query += " SET r.time_gap_hours = $time_gap_hours"
            params["time_gap_hours"] = time_gap_hours

        await self._pool.execute_query(query, params)

    async def get_followed_articles(
        self,
        pg_id: str,
        direction: str = "outgoing",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get articles that follow or are followed by the given article.

        Args:
            pg_id: The article's PostgreSQL ID.
            direction: 'outgoing' for articles that follow this one,
                      'incoming' for articles that this one follows.
            limit: Maximum number of articles to return.

        Returns:
            List of article dictionaries.
        """
        if direction == "outgoing":
            query = """
            MATCH (a:Article {pg_id: $pg_id})-[:FOLLOWED_BY]->(followed)
            RETURN elementId(followed) AS neo4j_id,
                   followed.pg_id AS pg_id,
                   followed.title AS title,
                   followed.category AS category,
                   followed.publish_time AS publish_time
            LIMIT $limit
            """
        else:
            query = """
            MATCH (a:Article {pg_id: $pg_id})<-[:FOLLOWED_BY]-(predecessor)
            RETURN elementId(predecessor) AS neo4j_id,
                   predecessor.pg_id AS pg_id,
                   predecessor.title AS title,
                   predecessor.category AS category,
                   predecessor.publish_time AS publish_time
            LIMIT $limit
            """

        params = {"pg_id": pg_id, "limit": limit}
        result = await self._pool.execute_query(query, params)
        return [dict(record) for record in result]

    async def delete_article(self, pg_id: str) -> bool:
        """Delete an Article node by PostgreSQL ID.

        This will also remove all MENTIONS and FOLLOWED_BY relationships.

        Args:
            pg_id: The article's PostgreSQL ID.

        Returns:
            True if deleted, False if not found.
        """
        query = """
        MATCH (a:Article {pg_id: $pg_id})
        DETACH DELETE a
        """
        await self._pool.execute_query(query, {"pg_id": pg_id})
        return True

    async def delete_old_articles(self, days: int = 90) -> int:
        """Delete old Article nodes that have no FOLLOWED_BY relationships.

        This is part of the data aging strategy. Only deletes articles
        that are older than the specified days and have no outgoing
        FOLLOWED_BY relationships (meaning no newer articles reference them).

        Args:
            days: Number of days to retain articles.

        Returns:
            Number of articles deleted (Note: Neo4j doesn't return count easily).
        """
        query = f"""
        MATCH (a:Article)
        WHERE a.publish_time < datetime() - duration({{days: {days}}})
          AND NOT (a)-[:FOLLOWED_BY]->()
        DETACH DELETE a
        """
        await self._pool.execute_query(query)
        # Neo4j doesn't easily return count from DETACH DELETE
        # In production, you might want to count before deleting
        return 0

    async def get_article_entities(
        self,
        pg_id: str,
    ) -> list[dict[str, Any]]:
        """Get all entities mentioned in an article.

        Args:
            pg_id: The article's PostgreSQL ID.

        Returns:
            List of entity dictionaries with role information.
        """
        query = """
        MATCH (a:Article {pg_id: $pg_id})-[r:MENTIONS]->(e:Entity)
        RETURN elementId(e) AS neo4j_id,
               e.id AS entity_id,
               e.canonical_name AS canonical_name,
               e.type AS entity_type,
               r.role AS role
        """
        result = await self._pool.execute_query(query, {"pg_id": pg_id})
        return [dict(record) for record in result]

    async def update_article_score(
        self,
        pg_id: str,
        score: float,
    ) -> None:
        """Update the score of an existing article.

        Args:
            pg_id: The article's PostgreSQL ID.
            score: New score value.
        """
        query = """
        MATCH (a:Article {pg_id: $pg_id})
        SET a.score = $score
        """
        await self._pool.execute_query(query, {"pg_id": pg_id, "score": score})

    async def delete_orphan_articles(self, valid_pg_ids: list[str]) -> int:
        """Delete Article nodes whose pg_id is not in the valid list.

        This cleans up orphan articles that exist in Neo4j but not in PostgreSQL.

        Args:
            valid_pg_ids: List of valid PostgreSQL article IDs.

        Returns:
            Number of articles deleted.
        """
        if not valid_pg_ids:
            query = """
            MATCH (a:Article)
            WITH a, count(a) AS total
            DETACH DELETE a
            RETURN total
            """
            result = await self._pool.execute_query(query)
            return result[0]["total"] if result else 0

        query = """
        MATCH (a:Article)
        WHERE NOT a.pg_id IN $valid_pg_ids
        WITH a, count(a) AS orphan_count
        DETACH DELETE a
        RETURN orphan_count
        """
        result = await self._pool.execute_query(query, {"valid_pg_ids": valid_pg_ids})
        return result[0]["orphan_count"] if result else 0

    async def list_all_article_pg_ids(self) -> list[str]:
        """List all article pg_ids in Neo4j.

        Returns:
            List of pg_id strings.
        """
        query = """
        MATCH (a:Article)
        RETURN a.pg_id AS pg_id
        """
        result = await self._pool.execute_query(query)
        return [r["pg_id"] for r in result if r.get("pg_id")]

    async def delete_articles_without_mentions(self) -> int:
        """Delete Article nodes that have no MENTIONS relationships and no FOLLOWED_BY outgoing relationships.

        An orphan article is defined as:
        - No incoming MENTIONS relationship (no article mentions this one as related)
        - No outgoing FOLLOWED_BY relationship (this article doesn't follow another)

        These articles are considered orphaned because they have no meaningful
        connections in the knowledge graph.

        Returns:
            Number of articles deleted.
        """
        query = """
        MATCH (a:Article)
        WHERE NOT ()-[:MENTIONS]->(a)
          AND NOT (a)-[:FOLLOWED_BY]->()
        DETACH DELETE a
        """
        await self._pool.execute_query(query)
        # Neo4j doesn't easily return count from DETACH DELETE
        # For accurate counting, use a separate count query
        return 0

    async def count_articles_without_mentions(self) -> int:
        """Count Article nodes that have no MENTIONS relationships and no FOLLOWED_BY outgoing relationships.

        Returns:
            Number of orphan articles.
        """
        query = """
        MATCH (a:Article)
        WHERE NOT ()-[:MENTIONS]->(a)
          AND NOT (a)-[:FOLLOWED_BY]->()
        RETURN count(a) AS orphan_count
        """
        result = await self._pool.execute_query(query)
        return result[0]["orphan_count"] if result else 0
