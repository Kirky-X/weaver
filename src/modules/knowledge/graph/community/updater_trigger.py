# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Update trigger policy collaborator for the incremental community updater.

Extracted from ``IncrementalCommunityUpdater``. Decides when an incremental
update or full rebuild should run based on pending-entity thresholds, time
intervals, entity-count change ratios, and community health.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.observability import get_logger
from modules.knowledge.graph.community.health.models import CommunityHealthStatus


def _to_datetime(value: object) -> datetime | None:
    """Coerce a stored timestamp value to an aware datetime.

    LadybugDB stores DateTime columns as INT64 epoch microseconds (per project
    migration rules), so metadata queries return ints instead of datetimes.
    Neo4j returns datetime objects directly. Normalize both forms here so that
    downstream arithmetic (``datetime - datetime``) does not raise
    ``TypeError: unsupported operand type(s) for -: 'datetime.datetime' and 'int'``.

    Args:
        value: Raw value from the graph database (datetime, int, or None).

    Returns:
        Timezone-aware datetime, or None when value is falsy/invalid.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    return None


if TYPE_CHECKING:
    from core.protocols import GraphPool
    from modules.knowledge.graph.community.updater import (
        CommunityStats,
        IncrementalCommunityUpdater,
    )
    from modules.knowledge.graph.community.updater_clustering import (
        SubgraphClusteringService,
    )

log = get_logger(__name__)


class UpdateTriggerPolicy:
    """Policy for triggering community updates and full rebuilds.

    Single responsibility: evaluate trigger conditions (pending-entity count,
    time interval, entity-count change ratio, rebuild interval, community
    health) and dispatch full rebuilds via the clustering service, reporting a
    structured result describing what (if anything) ran.

    Args:
        pool: Graph database connection pool.
        update_threshold: Minimum pending entities to trigger update.
        interval_minutes: Minimum minutes between incremental updates.
        full_rebuild_interval_days: Days between full rebuilds.
        clustering_service: Collaborator that runs full/incremental rebuilds.
        updater: Owning incremental updater, used for health checks and repair.
    """

    ENTITY_CHANGE_THRESHOLD: float = 0.10

    def __init__(
        self,
        pool: GraphPool,
        update_threshold: int,
        interval_minutes: int,
        full_rebuild_interval_days: int,
        clustering_service: SubgraphClusteringService,
        updater: IncrementalCommunityUpdater,
    ) -> None:
        self._pool = pool
        self.update_threshold = update_threshold
        self.interval_minutes = interval_minutes
        self.full_rebuild_interval_days = full_rebuild_interval_days
        self._clustering_service = clustering_service
        self._updater = updater

    async def should_trigger(
        self,
        pending_count: int,
        last_update_at: datetime | None,
    ) -> bool:
        """Check if incremental update should be triggered.

        Args:
            pending_count: Number of pending entities since last update.
            last_update_at: Timestamp of last incremental update.

        Returns:
            True if update should be triggered.
        """
        # Condition 1: pending count >= threshold
        if pending_count >= self.update_threshold:
            log.info(
                "should_trigger_count_threshold",
                pending_count=pending_count,
                threshold=self.update_threshold,
            )
            return True

        # Condition 2: time interval passed AND has pending data
        if last_update_at and pending_count > 0:
            minutes_since = (datetime.now(UTC) - last_update_at).total_seconds() / 60
            if minutes_since >= self.interval_minutes:
                log.info(
                    "should_trigger_time_threshold",
                    minutes_since=minutes_since,
                    pending_count=pending_count,
                )
                return True

        return False

    async def check_and_run(self) -> dict[str, object]:
        """Unified entry point for community auto-scheduling.

        Checks all trigger conditions and runs full rebuild if any is met.

        Returns:
            Dict with triggered, reason, and optional details.
        """
        # Check if any communities exist
        community_count = await self._get_community_count()
        if community_count == 0:
            log.info("check_and_run_no_communities")
            result = await self._clustering_service.run_full_rebuild()
            return {
                "triggered": True,
                "reason": "no_communities_exist",
                "communities_created": result.communities_created,
                "entities_reassigned": result.entities_reassigned,
                "duration_seconds": result.duration_seconds,
            }

        # Check entity percentage change
        entity_change_exceeded, current_count, previous_count = await self._check_entity_change()
        if entity_change_exceeded:
            log.info(
                "check_and_run_entity_change_exceeded",
                current_count=current_count,
                previous_count=previous_count,
            )
            result = await self._clustering_service.run_full_rebuild()
            return {
                "triggered": True,
                "reason": "entity_change_exceeded",
                "current_entity_count": current_count,
                "previous_entity_count": previous_count,
                "communities_created": result.communities_created,
                "duration_seconds": result.duration_seconds,
            }

        # Check rebuild interval
        if await self.check_full_rebuild_needed():
            log.info("check_and_run_interval_exceeded")
            result = await self._clustering_service.run_full_rebuild()
            return {
                "triggered": True,
                "reason": "rebuild_interval_exceeded",
                "communities_created": result.communities_created,
                "duration_seconds": result.duration_seconds,
            }

        # Health check for degraded/critical status
        health_report = await self._updater._run_health_check()
        if health_report.status in (
            CommunityHealthStatus.DEGRADED,
            CommunityHealthStatus.CRITICAL,
        ):
            log.info(
                "check_and_run_health_check_failed",
                status=health_report.status.value,
                issues=len(health_report.issues),
            )
            repair_result = await self._updater._auto_repair(health_report.issues)
            return {
                "triggered": True,
                "reason": "health_check_failed",
                "health_status": health_report.status.value,
                "health_score": health_report.score,
                "repaired": repair_result.to_dict(),
            }

        # No conditions met
        return {
            "triggered": False,
            "reason": None,
            "health_status": health_report.status.value,
            "health_score": health_report.score,
        }

    async def force_rebuild(self) -> dict[str, object]:
        """Force full community rebuild unconditionally.

        Returns:
            Dict with triggered=True, reason='forced', and rebuild results.
        """
        log.info("force_rebuild_start")
        result = await self._clustering_service.run_full_rebuild()
        return {
            "triggered": True,
            "reason": "forced",
            "communities_created": result.communities_created,
            "modularity": result.modularity_after,
            "duration_seconds": result.duration_seconds,
        }

    async def _get_community_count(self) -> int:
        """Get total number of Community nodes.

        Returns:
            Count of Community nodes in Neo4j.
        """
        query = "MATCH (c:Community) RETURN count(c) AS total"
        try:
            result = await self._pool.execute_query(query)
            return result[0]["total"] if result and result[0] else 0
        except Exception:
            log.warning("community_count_failed", exc_info=True)
            return 0

    async def _check_entity_change(self) -> tuple[bool, int, int]:
        """Check if entity count change exceeds threshold.

        Compares current entity count with the count stored at last rebuild.

        Returns:
            Tuple of (exceeded, current_count, previous_count).
        """
        # Get current entity count
        current_query = """
        MATCH (e:Entity)
        WHERE (e.pruned IS NULL OR e.pruned = false)
        RETURN count(e) AS total
        """
        try:
            result = await self._pool.execute_query(current_query)
            current_count = result[0]["total"] if result and result[0] else 0
        except Exception:
            log.warning("check_entity_count_change_failed", exc_info=True)
            return False, 0, 0

        # Get previous count from metadata
        previous_query = """
        MATCH (m:_CommunityMetadata)
        RETURN m.entity_count AS previous_count
        """
        try:
            result = await self._pool.execute_query(previous_query)
            previous_count = result[0].get("previous_count", 0) if result and result[0] else 0
        except Exception:
            log.warning("community_metadata_query_failed", exc_info=True)
            return False, current_count, 0

        if previous_count is None:
            previous_count = 0

        # Calculate change ratio
        if previous_count > 0:
            change_ratio = abs(current_count - previous_count) / previous_count
            if change_ratio > self.ENTITY_CHANGE_THRESHOLD:
                return True, current_count, previous_count

        return False, current_count, previous_count

    async def get_stats(self) -> CommunityStats:
        """Get current community update statistics.

        Returns:
            CommunityStats with current state.
        """
        from modules.knowledge.graph.community.updater import CommunityStats

        stats = CommunityStats()

        # Get last update timestamps from metadata
        metadata_query = """
        MATCH (m:_CommunityMetadata)
        RETURN m.last_full_rebuild_at AS last_full_rebuild,
               m.last_incremental_update_at AS last_incremental,
               m.pending_entity_count AS pending_count
        """

        try:
            result = await self._pool.execute_query(metadata_query)
            if result and result[0]:
                row = result[0]
                stats.last_full_rebuild_at = _to_datetime(row.get("last_full_rebuild"))
                stats.last_incremental_update_at = _to_datetime(row.get("last_incremental"))
                stats.pending_entity_count = row.get("pending_count", 0)
        except Exception as exc:
            log.debug("get_community_stats_failed", error=str(exc))

        # Also get current community count
        community_count_query = """
        MATCH (c:Community)
        RETURN count(c) AS total
        """

        try:
            result = await self._pool.execute_query(community_count_query)
            stats.total_communities = result[0]["total"] if result and result[0] else 0
        except Exception:
            log.warning("community_count_in_stats_failed", exc_info=True)
            stats.total_communities = 0

        return stats

    async def check_full_rebuild_needed(self) -> bool:
        """Check if full rebuild is needed.

        Returns:
            True if full rebuild is needed.
        """
        stats = await self.get_stats()

        # Condition 1: Time since last full rebuild
        if stats.last_full_rebuild_at:
            days_since = (datetime.now(UTC) - stats.last_full_rebuild_at).total_seconds() / 86400
            if days_since >= self.full_rebuild_interval_days:
                log.info(
                    "full_rebuild_needed_time",
                    days_since=days_since,
                    threshold=self.full_rebuild_interval_days,
                )
                return True
        else:
            # Never done a full rebuild
            log.info("full_rebuild_needed_never")
            return True

        # Condition 2: Modularity degradation
        # Check if modularity has dropped cumulatively >0.05 over last 3 checks
        if len(stats.modularity_history) >= 3:
            recent = stats.modularity_history[-3:]
            if len(recent) >= 3:
                drop = recent[0] - recent[-1]
                if drop > 0.05:
                    log.info("full_rebuild_needed_modularity", drop=drop)
                    return True

        return False
