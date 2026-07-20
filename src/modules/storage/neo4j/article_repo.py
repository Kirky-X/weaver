# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Neo4j article repository for article graph operations.

After the Article node slim-down (design.md §D2), the graph Article node
stores only ``{pg_id, created_at}`` (Neo4j) / ``{id, pg_id}`` (LadybugDB).
Business fields (title / category / publish_time / score) are batch-fetched
from PostgreSQL via ``ArticleRepository.fetch_titles_by_pg_ids``.
"""

from __future__ import annotations

from typing import Any

from core.observability import get_logger
from core.protocols import GraphPool

log = get_logger(__name__)


class Neo4jArticleRepo:
    """Neo4j article repository.

    Handles article-related graph operations in Neo4j, including article
    node creation and FOLLOWED_BY relationships.

    Args:
        pool: Graph database pool (Neo4j or LadybugDB).
    """

    def __init__(self, pool: GraphPool) -> None:
        self._pool = pool

    async def create_article(
        self,
        article_id: str,
    ) -> str:
        """Create an Article node in Neo4j.

        After the Article node slim-down (design.md §D2), the graph node
        stores only ``pg_id`` (and ``created_at`` for audit). Title /
        category / publish_time / score are no longer persisted on the
        node — callers that need them must batch-fetch from PostgreSQL
        via ``ArticleRepository.fetch_titles_by_pg_ids``.

        Args:
            article_id: PostgreSQL UUID of the article.

        Returns:
            The Neo4j internal ID of the created article.
        """
        query = """
        MERGE (a:Article {pg_id: $pg_id})
        ON CREATE SET
            a.created_at = datetime()
        RETURN elementId(a) AS neo4j_id
        """
        params = {"pg_id": article_id}
        result = await self._pool.execute_query(query, params)
        if result:
            return result[0]["neo4j_id"]
        raise RuntimeError("Failed to create article node")

    async def create_articles_batch(
        self,
        articles: list[dict[str, Any]],
    ) -> list[str]:
        """Create multiple Article nodes in batch using UNWIND.

        After the slim-down, only ``pg_id`` is read from each article
        dict; other keys (title/category/publish_time/score) are
        silently ignored.

        Args:
            articles: List of dicts; each must contain ``pg_id``. Other
                keys are ignored.

        Returns:
            List of Neo4j internal IDs for created articles.
        """
        if not articles:
            return []

        query = """
        UNWIND $articles AS article
        MERGE (a:Article {pg_id: article.pg_id})
        ON CREATE SET
            a.created_at = datetime()
        RETURN elementId(a) AS neo4j_id
        """
        # Slim params: only pg_id is read by the Cypher.
        slim_articles = [{"pg_id": a.get("pg_id")} for a in articles]
        params = {"articles": slim_articles}
        result = await self._pool.execute_query(query, params)
        return [r["neo4j_id"] for r in result if r.get("neo4j_id")]

    async def find_article_by_id(self, article_id: str) -> dict[str, Any] | None:
        """Find an article node by article ID (pg_id).

        After the slim-down, returns only ``{neo4j_id, pg_id, created_at}``.
        Callers that need title/category/publish_time/score must
        batch-fetch from PostgreSQL via
        ``ArticleRepository.fetch_titles_by_pg_ids``.

        Args:
            article_id: The article UUID.

        Returns:
            Article dict if found, None otherwise.
        """
        query = """
        MATCH (a:Article {pg_id: $pg_id})
        RETURN elementId(a) AS neo4j_id,
               a.pg_id AS pg_id,
               a.created_at AS created_at
        """
        result = await self._pool.execute_query(query, {"pg_id": article_id})
        if result:
            return dict(result[0])
        return None

    async def find_article_by_graph_id(self, graph_id: str) -> dict[str, Any] | None:
        """Find an article node by graph database internal ID.

        After the slim-down, returns only ``{neo4j_id, pg_id, created_at}``.
        """
        query = """
        MATCH (a)
        WHERE elementId(a) = $neo4j_id
        RETURN elementId(a) AS neo4j_id,
               a.pg_id AS pg_id,
               a.created_at AS created_at
        """
        result = await self._pool.execute_query(query, {"neo4j_id": graph_id})
        if result:
            return dict(result[0])
        return None

    async def find_articles_by_pg_ids(
        self,
        pg_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Batch lookup of Article nodes by pg_id (P4 fix for N+1).

        Uses a single UNWIND + OPTIONAL MATCH query to fetch all
        existing articles in one round-trip. Missing pg_ids are
        absent from the result.

        Args:
            pg_ids: List of PostgreSQL article IDs to look up.

        Returns:
            Dict mapping each found pg_id to its article dict
            (``{neo4j_id, pg_id, created_at}``). Empty input is a
            no-op (no DB call).
        """
        if not pg_ids:
            return {}
        query = """
        UNWIND $pg_ids AS pid
        MATCH (a:Article {pg_id: pid})
        RETURN elementId(a) AS neo4j_id,
               a.pg_id AS pg_id,
               a.created_at AS created_at
        """
        result = await self._pool.execute_query(query, {"pg_ids": pg_ids})
        return {row["pg_id"]: dict(row) for row in result if row.get("pg_id")}

    async def create_followed_by_relation(
        self,
        from_article_id: str,
        to_article_id: str,
        time_gap_hours: float | None = None,
    ) -> None:
        """Create a FOLLOWED_BY relationship between two articles.

        Indicates that the 'from' article is followed by the 'to' article
        (e.g., in a series of coverage about the same event).

        Args:
            from_article_id: The source article's PostgreSQL ID.
            to_article_id: The target article's PostgreSQL ID.
            time_gap_hours: Optional time gap between articles in hours.
        """
        query = """
        MATCH (from:Article {pg_id: $from_pg_id})
        MATCH (to:Article {pg_id: $to_pg_id})
        MERGE (from)-[r:FOLLOWED_BY]->(to)
        """
        params = {
            "from_pg_id": from_article_id,
            "to_pg_id": to_article_id,
        }

        if time_gap_hours is not None:
            query += " SET r.time_gap_hours = $time_gap_hours"
            params["time_gap_hours"] = time_gap_hours

        await self._pool.execute_query(query, params)

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
        article_id: str,
        direction: str = "outgoing",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get articles that follow or are followed by the given article.

        After the slim-down, returns only ``{neo4j_id, pg_id, time_gap_hours}``.
        Callers needing title/category/publish_time must batch-fetch
        from PostgreSQL.

        Args:
            article_id: The article's PostgreSQL ID.
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
                   r.time_gap_hours AS time_gap_hours
            LIMIT $limit
            """
        else:
            query = """
            MATCH (a:Article {pg_id: $pg_id})<-[:FOLLOWED_BY]-(predecessor)
            RETURN elementId(predecessor) AS neo4j_id,
                   predecessor.pg_id AS pg_id,
                   r.time_gap_hours AS time_gap_hours
            LIMIT $limit
            """

        params = {"pg_id": article_id, "limit": limit}
        result = await self._pool.execute_query(query, params)
        return [dict(record) for record in result]

    async def delete_article(self, article_id: str) -> int:
        """Delete an Article node by PostgreSQL ID.

        This will also remove all MENTIONS and FOLLOWED_BY relationships.

        T051 LOW-1: return type unified to ``int`` (count of nodes
        actually deleted) to match LadybugArticleRepo. The previous
        ``bool`` return always returned ``True`` even when no node
        matched — an LSP inconsistency that hid silent no-ops (rule 12).
        Uses ``collect`` + ``size`` to compute the count *before*
        DETACH DELETE (counting after DELETE is unreliable in Neo4j).
        Same pattern as ``delete_old_articles``.

        Args:
            article_id: The article's PostgreSQL ID.

        Returns:
            Number of nodes actually deleted (0 if no match, 1 if a
            node was deleted).
        """
        query = """
        MATCH (a:Article {pg_id: $pg_id})
        WITH collect(a) AS articles
        UNWIND articles AS a
        DETACH DELETE a
        RETURN size(articles) AS deleted
        """
        result = await self._pool.execute_query(query, {"pg_id": article_id})
        if not result:
            return 0
        return int(result[0].get("deleted", 0))

    async def delete_old_articles(self, cutoff_pg_ids: list[str]) -> int:
        """Delete Article nodes whose pg_id is in ``cutoff_pg_ids``.

        After the slim-down, the Article node no longer carries
        ``publish_time``, so the cutoff cannot be computed inside the
        graph. Callers (writers) must query PostgreSQL for
        ``publish_time < NOW() - INTERVAL '$days days'`` and pass the
        resulting pg_ids here.

        Implementation notes:
        - Batched in chunks of ``DELETE_BATCH_SIZE`` to avoid a single
          huge transaction that would block the pipeline write path and
          risk OOM. Each chunk is its own ``execute_query`` call.
        - Cypher uses ``collect`` + ``size`` to compute the deleted
          count *before* DETACH DELETE (counting after DELETE is
          unreliable in Neo4j).

        Args:
            cutoff_pg_ids: List of pg_ids to delete. Empty list is a
                no-op (no DB call).

        Returns:
            Number of articles deleted.
        """
        if not cutoff_pg_ids:
            return 0

        # P7 fix: chunk to bound transaction size. 500 nodes x ~5 rels
        # each = ~2500 rels per transaction, well within Neo4j's
        # transaction state budget. Tuned for the 90-day retention
        # archive job which can pass tens of thousands of pg_ids.
        DELETE_BATCH_SIZE = 500
        query = """
        UNWIND $pg_ids AS pid
        MATCH (a:Article {pg_id: pid})
        WITH collect(a) AS articles
        UNWIND articles AS a
        DETACH DELETE a
        RETURN size(articles) AS deleted
        """
        total_deleted = 0
        for i in range(0, len(cutoff_pg_ids), DELETE_BATCH_SIZE):
            chunk = cutoff_pg_ids[i : i + DELETE_BATCH_SIZE]
            result = await self._pool.execute_query(query, {"pg_ids": chunk})
            if result:
                total_deleted += result[0].get("deleted", 0)
        return total_deleted

    async def get_article_entities(
        self,
        article_id: str,
    ) -> list[dict[str, Any]]:
        """Get all entities mentioned in an article.

        Args:
            article_id: The article's PostgreSQL ID.

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
        result = await self._pool.execute_query(query, {"pg_id": article_id})
        return [dict(record) for record in result]

    async def delete_orphan_articles(self, valid_article_ids: list[str]) -> int:
        """Delete Article nodes whose pg_id is not in the valid list.

        This cleans up orphan articles that exist in Neo4j but not in PostgreSQL.

        Args:
            valid_article_ids: List of valid PostgreSQL article IDs.

        Returns:
            Number of articles deleted.
        """
        if not valid_article_ids:
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
        result = await self._pool.execute_query(query, {"valid_pg_ids": valid_article_ids})
        return result[0]["orphan_count"] if result else 0

    async def list_all_article_ids(self) -> list[str]:
        """List all article IDs in Neo4j.

        Returns:
            List of article ID strings.
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

        LOW-2 (T051): previously this method executed the DETACH DELETE
        then hardcoded ``return 0``, leaving callers unable to distinguish
        "0 deleted" from "error swallowed" (Rule 12 violation). Now uses
        the same ``collect + size + DETACH DELETE`` pattern as
        ``delete_old_articles`` and the LadybugDB counterpart — the count
        is computed BEFORE the delete (counting after DELETE is unreliable
        in Neo4j).

        Returns:
            Number of articles deleted.
        """
        query = """
        MATCH (a:Article)
        WHERE NOT ()-[:MENTIONS]->(a)
          AND NOT (a)-[:FOLLOWED_BY]->()
        WITH collect(a) AS articles
        UNWIND articles AS a
        DETACH DELETE a
        RETURN size(articles) AS deleted
        """
        result = await self._pool.execute_query(query)
        if not result:
            return 0
        return int(result[0].get("deleted", 0))

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
