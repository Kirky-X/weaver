# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""LadybugDB article repository for article graph operations.

LadybugDB-adapted version of Neo4jArticleRepo.
Uses id property instead of elementId(), and timestamp integers instead of datetime().

After the Article node slim-down (design.md §D2), the graph Article node
stores only ``{id, pg_id}``. Business fields (title / category /
publish_time / score) are batch-fetched from PostgreSQL via
``ArticleRepository.fetch_titles_by_pg_ids``.
"""

from __future__ import annotations

import uuid
from typing import Any

from core.observability import get_logger

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
        article_id: str,
    ) -> str:
        """Create or update an article node.

        After the Article node slim-down (design.md §D2), the graph node
        stores only ``{id, pg_id}``. Title / category / publish_time /
        score are no longer persisted on the node — callers that need
        them must batch-fetch from PostgreSQL via
        ``ArticleRepository.fetch_titles_by_pg_ids``.

        P5 fix: replaced the find+CREATE two-round-trip pattern with a
        single MERGE. LadybugDB (Kùzu) does not support ``ON CREATE
        SET``, so ``CASE WHEN ... IS NULL`` replicates the semantics:
        the client-generated ``id`` is only written when the node is
        new. Requires the ``article_pg_id_idx`` index from
        ``ladybug_schema.py`` to avoid a full table scan.

        Args:
            article_id: PostgreSQL article ID (pg_id).

        Returns:
            The graph-internal id of the article node.

        Raises:
            RuntimeError: If the MERGE returns no rows (unexpected
                failure). LSP-aligned with Neo4jArticleRepo — callers
                must surface the failure rather than receive a
                fabricated id (rule 12).
        """
        generated_id = str(uuid.uuid4())
        query = """
        MERGE (a:Article {pg_id: $pg_id})
        SET a.id = CASE WHEN a.id IS NULL THEN $id ELSE a.id END
        RETURN a.id AS id
        """
        result = await self._pool.execute_query(
            query,
            {
                "id": generated_id,
                "pg_id": article_id,
            },
        )
        if result:
            return result[0]["id"]
        raise RuntimeError("Failed to create article node")

    async def create_articles_batch(
        self,
        articles: list[dict[str, Any]],
    ) -> list[str]:
        """Create multiple Article nodes in batch.

        After the slim-down, only ``pg_id`` is read from each article
        dict; other keys (title/category/publish_time/score) are
        silently ignored.

        P6 fix: replaced the per-article ``find_article_by_id`` loop
        (N round-trips) with a single OPTIONAL MATCH that returns the
        existence map. New articles are then CREATEd in one UNWIND.
        Reduces N+1 round-trips to 2 round-trips total. Requires the
        ``article_pg_id_idx`` index from ``ladybug_schema.py``.

        Args:
            articles: List of dicts; each must contain ``pg_id``. Other
                keys are ignored.

        Returns:
            List of graph-internal article IDs for created/updated articles.
        """
        if not articles:
            return []

        pg_ids = [a.get("pg_id") for a in articles if a.get("pg_id")]
        if not pg_ids:
            return []

        # Round 1: fetch existing id mapping in one query.
        existing_query = """
        UNWIND $pg_ids AS pid
        OPTIONAL MATCH (a:Article {pg_id: pid})
        RETURN pid, a.id AS existing_id
        """
        existing_result = await self._pool.execute_query(existing_query, {"pg_ids": pg_ids})
        existing_map: dict[str, str] = {}
        missing_pg_ids: list[str] = []
        for row in existing_result:
            pid = row.get("pid")
            existing_id = row.get("existing_id")
            if pid and existing_id:
                existing_map[pid] = existing_id
            elif pid:
                missing_pg_ids.append(pid)

        # Round 2: CREATE the missing articles in one batch.
        created_ids: list[str] = []
        if missing_pg_ids:
            to_create = [{"id": str(uuid.uuid4()), "pg_id": pid} for pid in missing_pg_ids]
            create_query = """
            UNWIND $articles AS article
            CREATE (a:Article {
                id: article.id,
                pg_id: article.pg_id
            })
            RETURN a.id AS id
            """
            create_result = await self._pool.execute_query(create_query, {"articles": to_create})
            created_ids = [r["id"] for r in create_result if r.get("id")]
            # Build pid -> created id mapping by zipping (UNWIND preserves order).
            for to_create_item, created_id in zip(to_create, created_ids, strict=False):
                existing_map[to_create_item["pg_id"]] = created_id

        # Return in the same order as the input articles list.
        return [existing_map[pid] for pid in pg_ids if pid in existing_map]

    async def find_article_by_id(self, article_id: str) -> dict[str, Any] | None:
        """Find an article by its article ID (pg_id).

        After the slim-down, returns only ``{id, pg_id}``. Callers that
        need title/category/publish_time/score must batch-fetch from
        PostgreSQL via ``ArticleRepository.fetch_titles_by_pg_ids``.
        """
        query = """
        MATCH (a:Article {pg_id: $pg_id})
        RETURN a.id AS id,
               a.pg_id AS pg_id
        """
        result = await self._pool.execute_query(query, {"pg_id": article_id})
        if result:
            return dict(result[0])
        return None

    async def find_article_by_graph_id(self, graph_id: str) -> dict[str, Any] | None:
        """Find an article by its graph database internal ID.

        After the slim-down, returns only ``{id, pg_id}``.
        """
        query = """
        MATCH (a:Article {id: $id})
        RETURN a.id AS id,
               a.pg_id AS pg_id
        """
        result = await self._pool.execute_query(query, {"id": graph_id})
        if result:
            return dict(result[0])
        return None

    async def find_articles_by_pg_ids(
        self,
        pg_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Batch lookup of Article nodes by pg_id (P4 fix for N+1).

        Uses a single UNWIND + MATCH query to fetch all existing
        articles in one round-trip. Missing pg_ids are absent from
        the result. Requires the ``article_pg_id_idx`` index from
        ``ladybug_schema.py`` to avoid a full table scan.

        Args:
            pg_ids: List of PostgreSQL article IDs to look up.

        Returns:
            Dict mapping each found pg_id to its article dict
            (``{id, pg_id}``). Empty input is a no-op (no DB call).
        """
        if not pg_ids:
            return {}
        query = """
        UNWIND $pg_ids AS pid
        MATCH (a:Article {pg_id: pid})
        RETURN a.id AS id,
               a.pg_id AS pg_id
        """
        result = await self._pool.execute_query(query, {"pg_ids": pg_ids})
        return {row["pg_id"]: dict(row) for row in result if row.get("pg_id")}

    async def create_followed_by_relation(
        self,
        from_article_id: str,
        to_article_id: str,
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
                "from_pg_id": from_article_id,
                "to_pg_id": to_article_id,
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
        article_id: str,
        direction: str = "outgoing",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get articles that follow or are followed by the given article.

        After the slim-down, returns only ``{id, pg_id, time_gap_hours}``.
        """
        if direction == "outgoing":
            query = """
            MATCH (a:Article {pg_id: $pg_id})-[r:FOLLOWED_BY]->(followed)
            RETURN followed.id AS id,
                   followed.pg_id AS pg_id,
                   r.time_gap_hours AS time_gap_hours
            LIMIT $limit
            """
        else:
            query = """
            MATCH (a:Article {pg_id: $pg_id})<-[r:FOLLOWED_BY]-(follower)
            RETURN follower.id AS id,
                   follower.pg_id AS pg_id,
                   r.time_gap_hours AS time_gap_hours
            LIMIT $limit
            """
        result = await self._pool.execute_query(query, {"pg_id": article_id, "limit": limit})
        return [dict(r) for r in result]

    async def delete_article(self, article_id: str) -> bool:
        """Delete an article and its relationships."""
        query = """
        MATCH (a:Article {pg_id: $pg_id})
        WITH a, COUNT(a) AS count
        DELETE a
        RETURN count
        """
        result = await self._pool.execute_query(query, {"pg_id": article_id})
        return bool(result and result[0].get("count", 0) > 0)

    async def delete_old_articles(self, cutoff_pg_ids: list[str]) -> int:
        """Delete Article nodes whose pg_id is in ``cutoff_pg_ids``.

        After the slim-down, the Article node no longer carries
        ``publish_time``, so the cutoff cannot be computed inside the
        graph. Callers (writers) must query PostgreSQL for
        ``publish_time < NOW() - INTERVAL '$days days'`` and pass the
        resulting pg_ids here.

        Implementation notes:
        - Cypher uses ``collect`` + ``size`` to compute the deleted
          count *before* DETACH DELETE (counting after DELETE is
          unreliable — Kùzu may return 0 or stale values).
        - Batched in chunks of ``DELETE_BATCH_SIZE`` to bound
          transaction size and avoid blocking the single-writer
          LadybugDB lock for too long.

        Args:
            cutoff_pg_ids: List of pg_ids to delete. Empty list is a
                no-op (no DB call).

        Returns:
            Number of articles deleted.
        """
        if not cutoff_pg_ids:
            return 0

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

    async def get_article_entities(self, article_id: str) -> list[dict[str, Any]]:
        """Get all entities mentioned by an article."""
        query = """
        MATCH (a:Article {pg_id: $pg_id})-[r:MENTIONS]->(e:Entity)
        RETURN e.id AS entity_id,
               e.canonical_name AS canonical_name,
               e.type AS type,
               r.role AS role
        """
        result = await self._pool.execute_query(query, {"pg_id": article_id})
        return [dict(r) for r in result]

    async def delete_orphan_articles(self, valid_article_ids: list[str]) -> int:
        """Delete articles that don't exist in PostgreSQL."""
        # Find orphan articles
        query = """
        MATCH (a:Article)
        RETURN a.pg_id AS pg_id
        """
        result = await self._pool.execute_query(query)
        orphan_pg_ids = [r["pg_id"] for r in result if r["pg_id"] not in valid_article_ids]
        count = 0
        for pg_id in orphan_pg_ids:
            await self.delete_article(pg_id)
            count += 1
        return count

    async def list_all_article_ids(self) -> list[str]:
        """List all article IDs."""
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
