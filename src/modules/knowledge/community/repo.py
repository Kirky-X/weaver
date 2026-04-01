# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Neo4j community repository for community graph operations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from core.db.neo4j import Neo4jPool
from core.observability.logging import get_logger
from modules.knowledge.community.models import Community, CommunityReport

log = get_logger("neo4j_community_repo")


class Neo4jCommunityRepo:
    """Neo4j repository for community CRUD operations.

    Handles community and community report persistence in Neo4j.

    Args:
        pool: Neo4j connection pool.
    """

    def __init__(self, pool: Neo4jPool) -> None:
        self._pool = pool

    async def ensure_constraints(self) -> None:
        """Create uniqueness constraints and indexes for Community nodes."""
        constraints = [
            # Community ID uniqueness
            """
            CREATE CONSTRAINT community_id_unique IF NOT EXISTS
            FOR (c:Community) REQUIRE c.id IS UNIQUE
            """,
            # CommunityReport ID uniqueness
            """
            CREATE CONSTRAINT community_report_id_unique IF NOT EXISTS
            FOR (r:CommunityReport) REQUIRE r.id IS UNIQUE
            """,
        ]

        indexes = [
            # Index on level for efficient level-based queries
            "CREATE INDEX community_level_index IF NOT EXISTS FOR (c:Community) ON (c.level)",
            # Index on period for time-based queries
            "CREATE INDEX community_period_index IF NOT EXISTS FOR (c:Community) ON (c.period)",
            # Index on community_id for report lookups
            "CREATE INDEX community_report_community_id_index IF NOT EXISTS FOR (r:CommunityReport) ON (r.community_id)",
        ]

        for constraint in constraints:
            try:
                await self._pool.execute_query(constraint)
                log.debug("neo4j_constraint_created", constraint=constraint[:60])
            except Exception as exc:
                log.debug("neo4j_constraint_check", error=str(exc))

        for index in indexes:
            try:
                await self._pool.execute_query(index)
                log.debug("neo4j_index_created", index=index[:60])
            except Exception as exc:
                log.debug("neo4j_index_check", error=str(exc))

    async def delete_all_communities(self) -> int:
        """Delete all communities, reports, and their relationships.

        Returns:
            Number of communities deleted.
        """
        query = """
        MATCH (c:Community)
        WITH c, count(c) AS total
        DETACH DELETE c
        RETURN total
        """
        result = await self._pool.execute_query(query)
        if result:
            return result[0].get("total", 0)
        return 0

    async def create_community(
        self,
        community_id: str,
        title: str,
        level: int,
        parent_id: str | None = None,
        entity_count: int = 0,
        rank: float = 1.0,
        period: str | None = None,
        modularity: float | None = None,
    ) -> str:
        """Create a new Community node.

        Args:
            community_id: UUID for the community.
            title: Human-readable title.
            level: Hierarchy level.
            parent_id: Parent community ID.
            entity_count: Number of entities.
            rank: Importance ranking.
            period: Detection period (YYYY-MM-DD).
            modularity: Modularity score.

        Returns:
            The created community ID.
        """
        query = """
        CREATE (c:Community {
            id: $id,
            title: $title,
            level: $level,
            parent_id: $parent_id,
            entity_count: $entity_count,
            rank: $rank,
            period: $period,
            modularity: $modularity,
            created_at: datetime(),
            updated_at: datetime()
        })
        RETURN c.id AS id
        """
        params = {
            "id": community_id,
            "title": title,
            "level": level,
            "parent_id": parent_id,
            "entity_count": entity_count,
            "rank": rank,
            "period": period or datetime.now(UTC).date().isoformat(),
            "modularity": modularity,
        }
        result = await self._pool.execute_query(query, params)
        if result:
            return result[0]["id"]
        raise RuntimeError("Failed to create community")

    async def add_entity_to_community(
        self,
        community_id: str,
        entity_canonical_name: str,
        entity_type: str,
    ) -> bool:
        """Add an entity to a community via HAS_ENTITY relationship.

        Args:
            community_id: Community UUID.
            entity_canonical_name: Entity's canonical name.
            entity_type: Entity's type.

        Returns:
            True if relationship created.
        """
        query = """
        MATCH (c:Community {id: $community_id})
        MATCH (e:Entity {canonical_name: $entity_name, type: $entity_type})
        MERGE (c)-[:HAS_ENTITY]->(e)
        RETURN c.id AS id
        """
        params = {
            "community_id": community_id,
            "entity_name": entity_canonical_name,
            "entity_type": entity_type,
        }
        result = await self._pool.execute_query(query, params)
        return bool(result)

    async def add_entities_batch(
        self,
        assignments: list[dict[str, Any]],
    ) -> int:
        """Add multiple entities to communities in batch.

        Args:
            assignments: List of dicts with community_id, entity_name, entity_type.

        Returns:
            Number of relationships created.
        """
        if not assignments:
            return 0

        query = """
        UNWIND $assignments AS a
        MATCH (c:Community {id: a.community_id})
        MATCH (e:Entity {canonical_name: a.entity_name, type: a.entity_type})
        MERGE (c)-[:HAS_ENTITY]->(e)
        RETURN count(c) AS total
        """
        result = await self._pool.execute_query(query, {"assignments": assignments})
        if result:
            return result[0].get("total", 0)
        return 0

    async def create_parent_relationship(
        self,
        child_id: str,
        parent_id: str,
    ) -> bool:
        """Create PARENT_COMMUNITY relationship.

        Args:
            child_id: Child community ID.
            parent_id: Parent community ID.

        Returns:
            True if relationship created.
        """
        query = """
        MATCH (child:Community {id: $child_id})
        MATCH (parent:Community {id: $parent_id})
        MERGE (child)-[:PARENT_COMMUNITY]->(parent)
        RETURN child.id AS id
        """
        result = await self._pool.execute_query(
            query, {"child_id": child_id, "parent_id": parent_id}
        )
        return bool(result)

    async def get_community(self, community_id: str) -> Community | None:
        """Get a community by ID.

        Args:
            community_id: Community UUID.

        Returns:
            Community instance or None.
        """
        query = """
        MATCH (c:Community {id: $community_id})
        OPTIONAL MATCH (c)-[:HAS_ENTITY]->(e:Entity)
        WITH c, collect(e.canonical_name) AS entity_names
        RETURN c.id AS id,
               c.title AS title,
               c.level AS level,
               c.parent_id AS parent_id,
               c.entity_count AS entity_count,
               c.rank AS rank,
               c.period AS period,
               c.modularity AS modularity,
               c.created_at AS created_at,
               c.updated_at AS updated_at,
               entity_names AS entity_ids
        """
        result = await self._pool.execute_query(query, {"community_id": community_id})
        if result:
            return Community.from_neo4j(dict(result[0]))
        return None

    async def list_communities(
        self,
        level: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Community]:
        """List communities, optionally filtered by level.

        Args:
            level: Optional level filter.
            limit: Maximum results.
            offset: Result offset.

        Returns:
            List of Community instances.
        """
        if level is not None:
            query = """
            MATCH (c:Community)
            WHERE c.level = $level
            RETURN c.id AS id,
                   c.title AS title,
                   c.level AS level,
                   c.parent_id AS parent_id,
                   c.entity_count AS entity_count,
                   c.rank AS rank,
                   c.period AS period,
                   c.modularity AS modularity
            ORDER BY c.rank DESC
            SKIP $offset
            LIMIT $limit
            """
            params = {"level": level, "limit": limit, "offset": offset}
        else:
            query = """
            MATCH (c:Community)
            RETURN c.id AS id,
                   c.title AS title,
                   c.level AS level,
                   c.parent_id AS parent_id,
                   c.entity_count AS entity_count,
                   c.rank AS rank,
                   c.period AS period,
                   c.modularity AS modularity
            ORDER BY c.level, c.rank DESC
            SKIP $offset
            LIMIT $limit
            """
            params = {"limit": limit, "offset": offset}

        result = await self._pool.execute_query(query, params)
        return [Community.from_neo4j(dict(r)) for r in result]

    async def count_communities(self, level: int | None = None) -> int:
        """Count total communities.

        Args:
            level: Optional level filter.

        Returns:
            Number of communities.
        """
        if level is not None:
            query = "MATCH (c:Community) WHERE c.level = $level RETURN count(c) AS total"
            result = await self._pool.execute_query(query, {"level": level})
        else:
            query = "MATCH (c:Community) RETURN count(c) AS total"
            result = await self._pool.execute_query(query)

        if result:
            return result[0].get("total", 0)
        return 0

    # ── Community Report Methods ─────────────────────────────────────

    async def create_report(
        self,
        community_id: str,
        title: str,
        summary: str,
        full_content: str,
        key_entities: list[str],
        key_relationships: list[str],
        rank: float = 5.0,
    ) -> str:
        """Create a community report.

        Args:
            community_id: ID of the community.
            title: Report title.
            summary: Short summary.
            full_content: Full report content.
            key_entities: List of key entity names.
            key_relationships: List of key relationship descriptions.
            rank: Importance ranking.

        Returns:
            Report ID.
        """
        report_id = str(uuid.uuid4())
        query = """
        MATCH (c:Community {id: $community_id})
        CREATE (r:CommunityReport {
            id: $report_id,
            community_id: $community_id,
            title: $title,
            summary: $summary,
            full_content: $full_content,
            key_entities: $key_entities,
            key_relationships: $key_relationships,
            rank: $rank,
            stale: false,
            created_at: datetime(),
            updated_at: datetime()
        })
        CREATE (r)-[:REPORTS_ON]->(c)
        RETURN r.id AS id
        """
        params = {
            "report_id": report_id,
            "community_id": community_id,
            "title": title,
            "summary": summary,
            "full_content": full_content,
            "key_entities": key_entities,
            "key_relationships": key_relationships,
            "rank": rank,
        }
        result = await self._pool.execute_query(query, params)
        if result:
            return result[0]["id"]
        raise RuntimeError("Failed to create community report")

    async def get_report(self, community_id: str) -> CommunityReport | None:
        """Get the report for a community.

        Args:
            community_id: Community UUID.

        Returns:
            CommunityReport or None.
        """
        query = """
        MATCH (r:CommunityReport {community_id: $community_id})
        RETURN r.id AS id,
               r.community_id AS community_id,
               r.title AS title,
               r.summary AS summary,
               r.full_content AS full_content,
               r.key_entities AS key_entities,
               r.key_relationships AS key_relationships,
               r.rank AS rank,
               r.full_content_embedding AS full_content_embedding,
               r.stale AS stale,
               r.created_at AS created_at,
               r.updated_at AS updated_at
        """
        result = await self._pool.execute_query(query, {"community_id": community_id})
        if result:
            return CommunityReport.from_neo4j(dict(result[0]))
        return None

    async def update_report_embedding(
        self,
        report_id: str,
        embedding: list[float],
    ) -> bool:
        """Update report's vector embedding.

        Args:
            report_id: Report UUID.
            embedding: Vector embedding.

        Returns:
            True if updated.
        """
        query = """
        MATCH (r:CommunityReport {id: $report_id})
        SET r.full_content_embedding = $embedding,
            r.updated_at = datetime()
        RETURN r.id AS id
        """
        result = await self._pool.execute_query(
            query, {"report_id": report_id, "embedding": embedding}
        )
        return bool(result)

    async def mark_report_stale(self, community_id: str) -> bool:
        """Mark a community report as stale.

        Args:
            community_id: Community UUID.

        Returns:
            True if marked stale.
        """
        query = """
        MATCH (r:CommunityReport {community_id: $community_id})
        SET r.stale = true, r.updated_at = datetime()
        RETURN r.id AS id
        """
        result = await self._pool.execute_query(query, {"community_id": community_id})
        return bool(result)

    async def delete_report(self, community_id: str) -> bool:
        """Delete a community report.

        Args:
            community_id: Community UUID.

        Returns:
            True if deleted.
        """
        query = """
        MATCH (r:CommunityReport {community_id: $community_id})
        DETACH DELETE r
        RETURN count(r) AS deleted
        """
        result = await self._pool.execute_query(query, {"community_id": community_id})
        return bool(result)

    async def find_similar_reports(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        level: int | None = None,
    ) -> list[tuple[CommunityReport, float]]:
        """Find similar community reports using vector similarity.

        Args:
            query_embedding: Query vector.
            top_k: Number of results.
            level: Optional level filter.

        Returns:
            List of (CommunityReport, similarity_score) tuples.
        """
        if level is not None:
            cypher = """
            MATCH (r:CommunityReport)-[:REPORTS_ON]->(c:Community)
            WHERE c.level = $level AND r.full_content_embedding IS NOT NULL
            WITH r, vector.similarity.cosine(r.full_content_embedding, $embedding) AS score
            WHERE score > 0.0
            RETURN r.id AS id,
                   r.community_id AS community_id,
                   r.title AS title,
                   r.summary AS summary,
                   r.full_content AS full_content,
                   r.key_entities AS key_entities,
                   r.key_relationships AS key_relationships,
                   r.rank AS rank,
                   score
            ORDER BY score DESC
            LIMIT $top_k
            """
            params = {"embedding": query_embedding, "level": level, "top_k": top_k}
        else:
            cypher = """
            MATCH (r:CommunityReport)
            WHERE r.full_content_embedding IS NOT NULL
            WITH r, vector.similarity.cosine(r.full_content_embedding, $embedding) AS score
            WHERE score > 0.0
            RETURN r.id AS id,
                   r.community_id AS community_id,
                   r.title AS title,
                   r.summary AS summary,
                   r.full_content AS full_content,
                   r.key_entities AS key_entities,
                   r.key_relationships AS key_relationships,
                   r.rank AS rank,
                   score
            ORDER BY score DESC
            LIMIT $top_k
            """
            params = {"embedding": query_embedding, "top_k": top_k}

        result = await self._pool.execute_query(cypher, params)
        return [(CommunityReport.from_neo4j(dict(r)), r.get("score", 0.0)) for r in result]

    # ── Metrics Methods ─────────────────────────────────────

    async def get_community_metrics(self) -> dict[str, Any]:
        """Get overall community metrics.

        Returns:
            Dictionary with community statistics.
        """
        query = """
        MATCH (c:Community)
        WITH count(c) AS total_communities,
             max(c.level) AS max_level,
             avg(c.entity_count) AS avg_size,
             max(c.entity_count) AS max_size,
             min(c.entity_count) AS min_size
        OPTIONAL MATCH (c2:Community)
        WHERE c2.level = 0
        WITH total_communities, max_level, avg_size, max_size, min_size, count(c2) AS leaf_count
        OPTIONAL MATCH (r:CommunityReport)
        WITH total_communities, max_level, avg_size, max_size, min_size, leaf_count, count(r) AS reports
        OPTIONAL MATCH (c3:Community)-[:HAS_ENTITY]->(e:Entity)
        WHERE NOT (e)-[:RELATED_TO]-()
        WITH total_communities, max_level, avg_size, max_size, min_size, leaf_count, reports, count(DISTINCT c3) AS orphan_communities
        RETURN total_communities,
               max_level + 1 AS levels,
               avg_size,
               max_size,
               min_size,
               leaf_count,
               reports,
               orphan_communities
        """
        result = await self._pool.execute_query(query)
        if result:
            return dict(result[0])
        return {
            "total_communities": 0,
            "levels": 0,
            "avg_size": 0.0,
            "max_size": 0,
            "min_size": 0,
            "leaf_count": 0,
            "reports": 0,
            "orphan_communities": 0,
        }

    async def get_level_distribution(self) -> list[dict[str, int]]:
        """Get distribution of communities by level.

        Returns:
            List of {level, count} dicts.
        """
        query = """
        MATCH (c:Community)
        RETURN c.level AS level, count(c) AS count
        ORDER BY level
        """
        result = await self._pool.execute_query(query)
        return [{"level": r.get("level", 0), "count": r.get("count", 0)} for r in result]
