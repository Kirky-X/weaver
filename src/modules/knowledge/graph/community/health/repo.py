# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Community health repository for diagnostic queries.

Provides data access methods for community health diagnostics.
All methods are read-only and do not modify the graph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.protocols import GraphPool

log = get_logger("community_health_repo")


class CommunityHealthRepo:
    """Repository for community health diagnostic queries.

    Provides read-only queries for diagnosing community health issues.
    Does not modify any data - all queries are SELECT-only.

    Implements: CommunityHealthDataReader
    """

    def __init__(self, pool: GraphPool) -> None:
        """Initialize the health repository.

        Args:
            pool: Graph database connection pool.
        """
        self._pool = pool

    async def find_empty_communities(self) -> list[dict[str, Any]]:
        """Find communities with no associated entities.

        A community is considered empty if it has no HAS_ENTITY relationships
        to Entity nodes. Level >= 0 filter excludes orphan communities.

        Returns:
            List of dicts with community_id, title, level.
        """
        query = """
        MATCH (c:Community)
        WHERE NOT (c)-[:HAS_ENTITY]->(:Entity)
          AND c.level >= 0
        RETURN c.id AS community_id, c.title AS title, c.level AS level
        ORDER BY c.level DESC, c.title
        """

        try:
            results = await self._pool.execute_query(query)
            return [dict(r) for r in results if r.get("community_id")]
        except Exception as exc:
            log.error("find_empty_communities_failed", error=str(exc))
            return []

    async def find_entity_count_mismatches(self) -> list[dict[str, Any]]:
        """Find communities where stored entity_count doesn't match actual count.

        Compares the stored entity_count property with the actual number
        of HAS_ENTITY relationships to non-pruned entities.

        Returns:
            List of dicts with community_id, stored_count, actual_count.
        """
        query = """
        MATCH (c:Community)
        OPTIONAL MATCH (c)-[:HAS_ENTITY]->(e:Entity)
        WHERE (e.pruned IS NULL OR e.pruned = false)
        WITH c, count(e) AS actual_count
        WHERE c.entity_count <> actual_count
        RETURN c.id AS community_id,
               c.entity_count AS stored_count,
               actual_count
        ORDER BY abs(c.entity_count - actual_count) DESC
        """

        try:
            results = await self._pool.execute_query(query)
            return [dict(r) for r in results if r.get("community_id")]
        except Exception as exc:
            log.error("find_entity_count_mismatches_failed", error=str(exc))
            return []

    async def find_missing_reports(self) -> list[dict[str, Any]]:
        """Find communities without reports.

        Finds communities that don't have a CommunityReport via
        REPORTS_ON relationship.

        Returns:
            List of dicts with community_id, title, level.
        """
        query = """
        MATCH (c:Community)
        WHERE c.level >= 0
          AND NOT EXISTS((c)<-[:REPORTS_ON]-(:CommunityReport))
        RETURN c.id AS community_id, c.title AS title, c.level AS level
        ORDER BY c.level DESC, c.title
        """

        try:
            results = await self._pool.execute_query(query)
            return [dict(r) for r in results if r.get("community_id")]
        except Exception as exc:
            log.error("find_missing_reports_failed", error=str(exc))
            return []

    async def find_stale_reports(self, days_threshold: int = 7) -> list[dict[str, Any]]:
        """Find communities with stale or outdated reports.

        A report is considered stale if:
        - The stale flag is set to true, OR
        - It hasn't been updated in the specified number of days

        Args:
            days_threshold: Number of days after which a report is considered stale.

        Returns:
            List of dicts with community_id, report_id, stale, updated_at.
        """
        query = """
        MATCH (r:CommunityReport)-[:REPORTS_ON]->(c:Community)
        WHERE r.stale = true
           OR r.updated_at < datetime() - duration('P' + $days + 'D')
        RETURN c.id AS community_id,
               r.id AS report_id,
               r.stale AS stale,
               r.updated_at AS updated_at
        ORDER BY r.updated_at ASC
        """

        try:
            results = await self._pool.execute_query(query, {"days": days_threshold})
            return [dict(r) for r in results if r.get("community_id")]
        except Exception as exc:
            log.error("find_stale_reports_failed", error=str(exc))
            return []

    async def find_hierarchy_breaks(self) -> list[dict[str, Any]]:
        """Find communities with broken hierarchy references.

        Finds communities where parent_id points to a non-existent community.

        Returns:
            List of dicts with community_id, parent_id, level.
        """
        query = """
        MATCH (c:Community)
        WHERE c.parent_id IS NOT NULL
          AND NOT EXISTS((:Community {id: c.parent_id}))
        RETURN c.id AS community_id, c.parent_id AS parent_id, c.level AS level
        ORDER BY c.level DESC
        """

        try:
            results = await self._pool.execute_query(query)
            return [dict(r) for r in results if r.get("community_id")]
        except Exception as exc:
            log.error("find_hierarchy_breaks_failed", error=str(exc))
            return []

    async def get_overall_metrics(self) -> dict[str, Any]:
        """Get overall community metrics.

        Returns aggregate statistics about communities including
        total count, average size, level distribution, and report coverage.

        Returns:
            Dict with total_communities, avg_entity_count, max_level,
                 communities_with_reports, stale_report_count, empty_community_count.
        """
        query = """
        MATCH (c:Community)
        WITH count(c) AS total,
             avg(c.entity_count) AS avg_size,
             max(c.level) AS max_level,
             sum(CASE WHEN EXISTS((c)<-[:REPORTS_ON]-(:CommunityReport)) THEN 1 ELSE 0 END) AS with_report
        OPTIONAL MATCH (r:CommunityReport)
        WHERE r.stale = true
        WITH total, avg_size, max_level, with_report, count(r) AS stale_reports
        OPTIONAL MATCH (empty:Community)
        WHERE NOT (empty)-[:HAS_ENTITY]->(:Entity) AND empty.level >= 0
        WITH total, avg_size, max_level, with_report, stale_reports, count(empty) AS empty_count
        RETURN total AS total_communities,
               avg_size AS avg_entity_count,
               max_level,
               with_report AS communities_with_reports,
               stale_reports AS stale_report_count,
               empty_count AS empty_community_count
        """

        try:
            results = await self._pool.execute_query(query)
            if results and results[0]:
                return dict(results[0])
            return {
                "total_communities": 0,
                "avg_entity_count": 0.0,
                "max_level": 0,
                "communities_with_reports": 0,
                "stale_report_count": 0,
                "empty_community_count": 0,
            }
        except Exception as exc:
            log.error("get_overall_metrics_failed", error=str(exc))
            return {
                "total_communities": 0,
                "avg_entity_count": 0.0,
                "max_level": 0,
                "communities_with_reports": 0,
                "stale_report_count": 0,
                "empty_community_count": 0,
            }

    async def get_level_distribution(self) -> dict[int, int]:
        """Get distribution of communities by level.

        Returns:
            Dict mapping level number to count of communities.
        """
        query = """
        MATCH (c:Community)
        RETURN c.level AS level, count(c) AS count
        ORDER BY c.level
        """

        try:
            results = await self._pool.execute_query(query)
            return {r["level"]: r["count"] for r in results if r.get("level") is not None}
        except Exception as exc:
            log.error("get_level_distribution_failed", error=str(exc))
            return {}

    async def count_total_entities(self) -> int:
        """Count total non-pruned entities in the graph.

        Returns:
            Total entity count.
        """
        query = """
        MATCH (e:Entity)
        WHERE (e.pruned IS NULL OR e.pruned = false)
        RETURN count(e) AS total
        """

        try:
            results = await self._pool.execute_query(query)
            return results[0]["total"] if results and results[0] else 0
        except Exception as exc:
            log.error("count_total_entities_failed", error=str(exc))
            return 0

    async def count_unassigned_entities(self) -> int:
        """Count entities not assigned to any community.

        Returns:
            Count of entities without community assignment.
        """
        query = """
        MATCH (e:Entity)
        WHERE NOT (e)<-[:HAS_ENTITY]-(:Community)
          AND (e.pruned IS NULL OR e.pruned = false)
        RETURN count(e) AS total
        """

        try:
            results = await self._pool.execute_query(query)
            return results[0]["total"] if results and results[0] else 0
        except Exception as exc:
            log.error("count_unassigned_entities_failed", error=str(exc))
            return 0
