# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Graph community repository for community graph operations."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.db.graph_query_builders import GraphDatabaseType
from core.observability.logging import get_logger
from modules.knowledge.graph.community.models import Community, CommunityReport

if TYPE_CHECKING:
    from core.protocols import GraphPool

log = get_logger(__name__)


class Neo4jCommunityRepo:
    """Graph repository for community CRUD operations.

    Handles community and community report persistence.

    Implements: CommunityRepository

    Args:
        pool: Graph database connection pool.
    """

    def __init__(
        self,
        pool: GraphPool,
        database_type: GraphDatabaseType = GraphDatabaseType.NEO4J,
    ) -> None:
        self._pool = pool
        self._database_type = database_type

    def _now_ts(self) -> int:
        """Get current timestamp as integer for LadybugDB."""
        return int(time.time() * 1000)

    def _now_datetime(self) -> str:
        """Get datetime() expression based on database type."""
        if self._database_type == GraphDatabaseType.LADYBUG:
            return str(self._now_ts())
        return "datetime()"

    def _format_timestamp_params(self) -> tuple[str, str, int | None]:
        """Return (created_at_cypher, updated_at_cypher, now_value) based on database type.

        For Neo4j, returns ("datetime()", "datetime()", None) — timestamps are Cypher expressions.
        For LadybugDB, returns ("$created_at", "$updated_at", now_ms) — timestamps are parameters.
        """
        if self._database_type == GraphDatabaseType.LADYBUG:
            now = self._now_ts()
            return "$created_at", "$updated_at", now
        return "datetime(),", "datetime(),", None

    def _format_children_ids_param(self, children_ids: list[str] | None) -> tuple[str, str]:
        """Return (param_value_for_ladybug, param_value_for_neo4j) for children_ids.

        Args:
            children_ids: List of child community IDs, or None/empty.

        Returns:
            Tuple of (csv_string, json_string).
        """
        children_ids_csv = "" if not children_ids else ",".join(children_ids)
        children_ids_json = "[]" if not children_ids else json.dumps(children_ids)
        return children_ids_csv, children_ids_json

    async def ensure_constraints(self) -> None:
        """Create uniqueness constraints and indexes for Community nodes."""
        if self._database_type == GraphDatabaseType.LADYBUG:
            # LadybugDB doesn't support CREATE CONSTRAINT/INDEX via Cypher
            return

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
        if self._database_type == GraphDatabaseType.LADYBUG:
            # LadybugDB: No DETACH DELETE. Delete relationships first, then nodes.
            # Delete REPORTS_ON relationships first (from CommunityReport to Community)
            await self._pool.execute_query("MATCH ()-[r:REPORTS_ON]->() DELETE r")
            # Delete CommunityReport nodes
            await self._pool.execute_query("MATCH (r:CommunityReport) DELETE r")
            # Count communities before deletion
            count_result = await self._pool.execute_query(
                "MATCH (c:Community) RETURN count(c) AS total"
            )
            total = count_result[0].get("total", 0) if count_result else 0
            # Delete HAS_ENTITY relationships from communities
            await self._pool.execute_query("MATCH (c:Community)-[r:HAS_ENTITY]->() DELETE r")
            # Delete PARENT_COMMUNITY relationships (optional, may not exist in LadybugDB)
            try:
                await self._pool.execute_query(
                    "MATCH (c:Community)-[r:PARENT_COMMUNITY]->() DELETE r"
                )
            except Exception as exc:
                log.debug("delete_parent_step", error=str(exc))
            # Delete community nodes
            await self._pool.execute_query("MATCH (c:Community) DELETE c")
            return total

        # Neo4j: Use DETACH DELETE
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
        children_ids: list[str] | None = None,
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
            children_ids: List of child community IDs.
            entity_count: Number of entities.
            rank: Importance ranking.
            period: Detection period (YYYY-MM-DD).
            modularity: Modularity score.

        Returns:
            The created community ID.
        """
        children_ids_csv, children_ids_json = self._format_children_ids_param(children_ids)
        created_at_cypher, updated_at_cypher, now_value = self._format_timestamp_params()
        query = (
            """
            CREATE (c:Community {
                id: $id,
                title: $title,
                level: $level,
                parent_id: $parent_id,
                children_ids: $children_ids,
                entity_count: $entity_count,
                rank: $rank,
                period: $period,
                modularity: $modularity,
                created_at: """
            + created_at_cypher
            + """
            updated_at: """
            + updated_at_cypher
            + """
        })
        RETURN c.id AS id
        """
        )
        params = {
            "id": community_id,
            "title": title,
            "level": level,
            "parent_id": parent_id,
            "children_ids": (
                children_ids_csv
                if self._database_type == GraphDatabaseType.LADYBUG
                else children_ids_json
            ),
            "entity_count": entity_count,
            "rank": rank,
            "period": period or datetime.now(UTC).date().isoformat(),
            "modularity": modularity,
        }
        if self._database_type == GraphDatabaseType.LADYBUG:
            params["created_at"] = now_value
            params["updated_at"] = now_value
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
        # LadybugDB: MERGE doesn't work for relationships, use CREATE
        if self._database_type == GraphDatabaseType.LADYBUG:
            # First get entity ID by canonical_name
            entity_query = """
            MATCH (e:Entity {canonical_name: $entity_name})
            RETURN e.id AS entity_id
            """
            entity_result = await self._pool.execute_query(
                entity_query, {"entity_name": entity_canonical_name}
            )
            if not entity_result or not entity_result[0].get("entity_id"):
                log.debug(
                    "entity_not_found_for_community",
                    entity_name=entity_canonical_name,
                )
                return False

            entity_id = entity_result[0]["entity_id"]
            # Use CREATE instead of MERGE for LadybugDB
            query = """
            MATCH (c:Community {id: $community_id})
            MATCH (e:Entity {id: $entity_id})
            CREATE (c)-[:HAS_ENTITY]->(e)
            RETURN c.id AS id
            """
            params = {
                "community_id": community_id,
                "entity_id": entity_id,
            }
        else:
            # Neo4j: MERGE works for relationships
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

        if self._database_type == GraphDatabaseType.LADYBUG:
            # LadybugDB: No UNWIND. Use individual MERGE queries.
            total = 0
            for a in assignments:
                try:
                    await self.add_entity_to_community(
                        a["community_id"], a["entity_name"], a["entity_type"]
                    )
                    total += 1
                except Exception as exc:
                    log.debug(
                        "add_entity_to_community_failed",
                        community_id=a["community_id"],
                        entity=a["entity_name"],
                        error=str(exc),
                    )
            return total

        # Neo4j: Use UNWIND for batch
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

    async def delete_community(self, community_id: str) -> bool:
        """Delete a single community and its relationships.

        Args:
            community_id: Community UUID to delete.

        Returns:
            True if deleted.
        """
        if self._database_type == GraphDatabaseType.LADYBUG:
            # LadybugDB: Cypher-style delete - check exists first, then delete
            # Note: DELETE in LadybugDB doesn't return results
            check_query = """
            MATCH (c:Community {id: $id})
            RETURN c.id AS id
            """
            exists = await self._pool.execute_query(check_query, {"id": community_id})
            if not exists:
                return False
            # Delete
            query = """
            MATCH (c:Community {id: $id})
            DELETE c
            """
            await self._pool.execute_query(query, {"id": community_id})
            return True
        else:
            # Neo4j: DETACH DELETE removes node and relationships
            query = """
            MATCH (c:Community {id: $id})
            DETACH DELETE c
            RETURN count(c) AS deleted
            """
            result = await self._pool.execute_query(query, {"id": community_id})
            return bool(result)

    async def update_children(
        self,
        community_id: str,
        children_ids: list[str],
    ) -> bool:
        """Update children_ids for a community.

        Args:
            community_id: Community UUID.
            children_ids: List of child community IDs.

        Returns:
            True if updated.
        """
        children_ids_json = json.dumps(children_ids)
        children_ids_csv = ",".join(children_ids)
        if self._database_type == GraphDatabaseType.LADYBUG:
            # LadybugDB: Cypher-style update (SET)
            query = """
            MATCH (c:Community {id: $id})
            SET c.children_ids = $children_ids, c.updated_at = $updated_at
            RETURN c.id AS id
            """
            params = {
                "id": community_id,
                "children_ids": children_ids_csv,
                "updated_at": self._now_ts(),
            }
        else:
            query = """
            MATCH (c:Community {id: $id})
            SET c.children_ids = $children_ids,
                c.updated_at = datetime()
            RETURN c.id AS id
            """
            params = {"id": community_id, "children_ids": children_ids_json}
        result = await self._pool.execute_query(query, params)
        return bool(result)

    async def get_community(self, community_id: str) -> Community | None:
        """Get a community by ID.

        Args:
            community_id: Community UUID.

        Returns:
            Community instance or None.
        """
        if self._database_type == GraphDatabaseType.LADYBUG:
            # LadybugDB: Cypher-style query (MATCH/RETURN)
            query = """
            MATCH (c:Community)
            WHERE c.id = $community_id
            RETURN c.id AS id,
                   c.title AS title,
                   c.level AS level,
                   c.parent_id AS parent_id,
                   c.children_ids AS children_ids,
                   c.entity_count AS entity_count,
                   c.rank AS rank,
                   c.period AS period,
                   c.modularity AS modularity,
                   c.created_at AS created_at,
                   c.updated_at AS updated_at
            """
            result = await self._pool.execute_query(query, {"community_id": community_id})
            if result:
                raw_data = dict(result[0])
                # Parse children_ids: LadybugDB uses CSV format
                children_ids_str = raw_data.get("children_ids", "")
                if children_ids_str:
                    raw_data["children_ids"] = children_ids_str.split(",")
                else:
                    raw_data["children_ids"] = []
                # LadybugDB doesn't have HAS_ENTITY rel, use empty list
                raw_data["entity_ids"] = []
                return Community.from_neo4j(raw_data)
            return None

        # Neo4j: Cypher query
        query = """
        MATCH (c:Community {id: $community_id})
        OPTIONAL MATCH (c)-[:HAS_ENTITY]->(e:Entity)
        WITH c, collect(e.canonical_name) AS entity_names
        RETURN c.id AS id,
               c.title AS title,
               c.level AS level,
               c.parent_id AS parent_id,
               c.children_ids AS children_ids,
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
            raw_data = dict(result[0])
            # Parse children_ids JSON string if present
            children_ids_str = raw_data.get("children_ids", "[]")
            if isinstance(children_ids_str, str):
                try:
                    raw_data["children_ids"] = json.loads(children_ids_str)
                except json.JSONDecodeError:
                    raw_data["children_ids"] = []
            return Community.from_neo4j(raw_data)
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
        if self._database_type == GraphDatabaseType.LADYBUG:
            now = self._now_ts()
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
                created_at: $created_at,
                updated_at: $updated_at
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
                "created_at": now,
                "updated_at": now,
            }
        else:
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
        if self._database_type == GraphDatabaseType.LADYBUG:
            # LadybugDB: No coalesce support, handle nulls in Python
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
                   r.stale AS stale,
                   r.created_at AS created_at,
                   r.updated_at AS updated_at
            """
        else:
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

    async def get_reports_existence(self, community_ids: list[str]) -> dict[str, bool]:
        """Batch check which communities have reports.

        Args:
            community_ids: List of community IDs to check.

        Returns:
            Dict mapping community_id to whether it has a report.
        """
        if not community_ids:
            return {}

        query = """
        MATCH (r:CommunityReport)
        WHERE r.community_id IN $community_ids
        RETURN r.community_id AS community_id
        """
        result = await self._pool.execute_query(query, {"community_ids": community_ids})
        # Start with all False, then set True for those that have reports
        has_report = dict.fromkeys(community_ids, False)
        for row in result:
            cid = row.get("community_id")
            if cid:
                has_report[cid] = True
        return has_report

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
        if self._database_type == GraphDatabaseType.LADYBUG:
            query = """
            MATCH (r:CommunityReport {id: $report_id})
            SET r.full_content_embedding = $embedding
            RETURN r.id AS id
            """
        else:
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
        if self._database_type == GraphDatabaseType.LADYBUG:
            # LadybugDB: No stale field in schema, just skip
            return True
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
        if self._database_type == GraphDatabaseType.LADYBUG:
            # LadybugDB: No DETACH DELETE. Delete relationship first.
            try:
                await self._pool.execute_query(
                    """
                MATCH (r:CommunityReport {community_id: $community_id})-[rel:REPORTS_ON]->()
                DELETE rel
                """,
                    {"community_id": community_id},
                )
            except Exception as exc:
                # Relationship may not exist, log but continue
                log.debug(
                    "delete_report_relation_skipped", community_id=community_id, error=str(exc)
                )
            query = """
            MATCH (r:CommunityReport {community_id: $community_id})
            DELETE r
            RETURN count(r) AS deleted
            """
        else:
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
        if self._database_type == GraphDatabaseType.LADYBUG:
            # LadybugDB: No vector.similarity.cosine. Use array_cosine_similarity.
            # Use coalesce for properties that may not exist.
            if level is not None:
                cypher = """
                MATCH (r:CommunityReport)-[:REPORTS_ON]->(c:Community)
                WHERE c.level = $level AND r.full_content_embedding IS NOT NULL
                WITH r, array_cosine_similarity(r.full_content_embedding, $embedding) AS score
                WHERE score > 0.0
                RETURN r.id AS id,
                       r.community_id AS community_id,
                       r.title AS title,
                       r.summary AS summary,
                       r.full_content AS full_content,
                       coalesce(r.key_entities, []) AS key_entities,
                       coalesce(r.key_relationships, []) AS key_relationships,
                       coalesce(r.rank, 1.0) AS rank,
                       score
                ORDER BY score DESC
                LIMIT $top_k
                """
            else:
                cypher = """
                MATCH (r:CommunityReport)
                WHERE r.full_content_embedding IS NOT NULL
                WITH r, array_cosine_similarity(r.full_content_embedding, $embedding) AS score
                WHERE score > 0.0
                RETURN r.id AS id,
                       r.community_id AS community_id,
                       r.title AS title,
                       r.summary AS summary,
                       r.full_content AS full_content,
                       coalesce(r.key_entities, []) AS key_entities,
                       coalesce(r.key_relationships, []) AS key_relationships,
                       coalesce(r.rank, 1.0) AS rank,
                       score
                ORDER BY score DESC
                LIMIT $top_k
                """
        else:
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
        if level is not None:
            params["level"] = level

        result = await self._pool.execute_query(cypher, params)
        return [(CommunityReport.from_neo4j(dict(r)), r.get("score", 0.0)) for r in result]

    # ── Metrics Methods ─────────────────────────────────────

    async def get_community_metrics(self) -> dict[str, Any]:
        """Get overall community metrics.

        Returns:
            Dictionary with community statistics.
        """
        if self._database_type == GraphDatabaseType.LADYBUG:
            # LadybugDB: Break complex WITH chain into individual queries
            metrics: dict[str, Any] = {
                "total_communities": 0,
                "levels": 0,
                "avg_size": 0.0,
                "max_size": 0,
                "min_size": 0,
                "leaf_count": 0,
                "reports": 0,
                "orphan_communities": 0,
            }

            # Total communities + basic stats
            result = await self._pool.execute_query("""
            MATCH (c:Community)
            RETURN count(c) AS total_communities,
                   max(c.level) AS max_level,
                   avg(c.entity_count) AS avg_size,
                   max(c.entity_count) AS max_size,
                   min(c.entity_count) AS min_size
            """)
            if result:
                metrics["total_communities"] = result[0].get("total_communities", 0)
                max_level = result[0].get("max_level", 0)
                metrics["levels"] = (max_level + 1) if max_level is not None else 0
                metrics["avg_size"] = result[0].get("avg_size", 0.0) or 0.0
                metrics["max_size"] = result[0].get("max_size", 0) or 0
                metrics["min_size"] = result[0].get("min_size", 0) or 0

            # Leaf count (level 0)
            result = await self._pool.execute_query(
                "MATCH (c:Community) WHERE c.level = 0 RETURN count(c) AS leaf_count"
            )
            if result:
                metrics["leaf_count"] = result[0].get("leaf_count", 0)

            # Report count
            result = await self._pool.execute_query(
                "MATCH (r:CommunityReport) RETURN count(r) AS reports"
            )
            if result:
                metrics["reports"] = result[0].get("reports", 0)

            return metrics

        # Neo4j: Use complex WITH chain
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
