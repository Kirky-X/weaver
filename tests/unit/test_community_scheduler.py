# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for community detection scheduler and auto-trigger functionality."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCommunityDetectionScheduler:
    """Tests for CommunityDetectionScheduler."""

    @pytest.fixture
    def mock_neo4j_pool(self):
        """Mock Neo4j pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[{"count": 100}])
        return pool

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        return redis

    @pytest.fixture
    def scheduler(self, mock_neo4j_pool, mock_redis):
        """Create scheduler instance."""
        from modules.scheduler.jobs import CommunityDetectionScheduler

        return CommunityDetectionScheduler(
            neo4j_pool=mock_neo4j_pool,
            redis_client=mock_redis,
        )

    @pytest.mark.asyncio
    async def test_check_triggers_when_no_communities_exist(
        self, scheduler, mock_neo4j_pool, mock_redis
    ):
        """Test that detection is triggered when no communities exist."""
        # Mock no communities
        with patch("modules.graph_store.community_repo.Neo4jCommunityRepo") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.count_communities = AsyncMock(return_value=0)
            mock_repo_class.return_value = mock_repo

            # Mock detector
            with patch(
                "modules.graph_store.community_detector.CommunityDetector"
            ) as mock_detector_class:
                mock_detector = MagicMock()
                mock_detector.rebuild_communities = AsyncMock(
                    return_value=MagicMock(
                        total_communities=10,
                        modularity=0.45,
                    )
                )
                mock_detector_class.return_value = mock_detector

                result = await scheduler.check_and_trigger_detection()

                assert result["triggered"] is True
                assert result["reason"] == "no_communities_exist"
                assert result["current_entity_count"] == 100

    @pytest.mark.asyncio
    async def test_check_triggers_on_entity_change_threshold(
        self, scheduler, mock_neo4j_pool, mock_redis
    ):
        """Test that detection triggers when entity change exceeds 10%."""
        from modules.scheduler.jobs import CommunityDetectionScheduler

        # Mock previous entity count (80 -> 100 = 25% change)
        mock_redis.get = AsyncMock(
            side_effect=lambda key: (
                "80" if key == CommunityDetectionScheduler.ENTITY_COUNT_KEY else None
            )
        )

        # Mock communities exist
        with patch("modules.graph_store.community_repo.Neo4jCommunityRepo") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.count_communities = AsyncMock(return_value=5)
            mock_repo_class.return_value = mock_repo

            # Mock recent rebuild
            mock_redis.get = AsyncMock(
                side_effect=lambda key: (
                    datetime.now(UTC).isoformat()
                    if key == CommunityDetectionScheduler.LAST_REBUILD_KEY
                    else "80" if key == CommunityDetectionScheduler.ENTITY_COUNT_KEY else None
                )
            )

            with patch(
                "modules.graph_store.community_detector.CommunityDetector"
            ) as mock_detector_class:
                mock_detector = MagicMock()
                mock_detector.rebuild_communities = AsyncMock(
                    return_value=MagicMock(
                        total_communities=10,
                        modularity=0.45,
                    )
                )
                mock_detector_class.return_value = mock_detector

                result = await scheduler.check_and_trigger_detection()

                assert result["triggered"] is True
                assert "entity_change" in result["reason"]

    @pytest.mark.asyncio
    async def test_check_triggers_on_time_threshold(self, scheduler, mock_neo4j_pool, mock_redis):
        """Test that detection triggers after 7 days since last rebuild."""
        from modules.scheduler.jobs import CommunityDetectionScheduler

        # Mock previous entity count same as current
        mock_redis.get = AsyncMock(
            side_effect=lambda key: (
                "100"
                if key == CommunityDetectionScheduler.ENTITY_COUNT_KEY
                else (
                    datetime(2024, 1, 1, tzinfo=UTC).isoformat()
                    if key == CommunityDetectionScheduler.LAST_REBUILD_KEY
                    else None
                )
            )
        )

        with patch("modules.graph_store.community_repo.Neo4jCommunityRepo") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.count_communities = AsyncMock(return_value=5)
            mock_repo_class.return_value = mock_repo

            with patch(
                "modules.graph_store.community_detector.CommunityDetector"
            ) as mock_detector_class:
                mock_detector = MagicMock()
                mock_detector.rebuild_communities = AsyncMock(
                    return_value=MagicMock(
                        total_communities=8,
                        modularity=0.42,
                    )
                )
                mock_detector_class.return_value = mock_detector

                result = await scheduler.check_and_trigger_detection()

                # Should trigger due to days_since_rebuild >= 7
                assert result["triggered"] is True
                assert "days_since_rebuild" in result["reason"]

    @pytest.mark.asyncio
    async def test_check_skips_when_conditions_not_met(
        self, scheduler, mock_neo4j_pool, mock_redis
    ):
        """Test that detection is skipped when conditions are not met."""
        from modules.scheduler.jobs import CommunityDetectionScheduler

        # Mock recent rebuild (< 7 days) and same entity count
        mock_redis.get = AsyncMock(
            side_effect=lambda key: (
                "100"
                if key == CommunityDetectionScheduler.ENTITY_COUNT_KEY
                else (
                    datetime.now(UTC).isoformat()
                    if key == CommunityDetectionScheduler.LAST_REBUILD_KEY
                    else None
                )
            )
        )

        with patch("modules.graph_store.community_repo.Neo4jCommunityRepo") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.count_communities = AsyncMock(return_value=5)
            mock_repo_class.return_value = mock_repo

            result = await scheduler.check_and_trigger_detection()

            assert result["triggered"] is False
            assert result["reason"] is None

    @pytest.mark.asyncio
    async def test_force_rebuild_always_triggers(self, scheduler, mock_neo4j_pool, mock_redis):
        """Test that force_rebuild always triggers detection."""
        with patch(
            "modules.graph_store.community_detector.CommunityDetector"
        ) as mock_detector_class:
            mock_detector = MagicMock()
            mock_detector.rebuild_communities = AsyncMock(
                return_value=MagicMock(
                    total_communities=12,
                    modularity=0.48,
                )
            )
            mock_detector_class.return_value = mock_detector

            result = await scheduler.force_rebuild()

            assert result["triggered"] is True
            assert result["reason"] == "forced"
            assert result["communities_created"] == 12

    @pytest.mark.asyncio
    async def test_updates_state_after_detection(self, scheduler, mock_neo4j_pool, mock_redis):
        """Test that state is updated after successful detection."""
        with patch("modules.graph_store.community_repo.Neo4jCommunityRepo") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.count_communities = AsyncMock(return_value=0)
            mock_repo_class.return_value = mock_repo

            with patch(
                "modules.graph_store.community_detector.CommunityDetector"
            ) as mock_detector_class:
                mock_detector = MagicMock()
                mock_detector.rebuild_communities = AsyncMock(
                    return_value=MagicMock(
                        total_communities=10,
                        modularity=0.45,
                    )
                )
                mock_detector_class.return_value = mock_detector

                await scheduler.check_and_trigger_detection()

                # Verify Redis state was updated
                mock_redis.set.assert_called()


class TestCommunityDetectionSchedulerConfig:
    """Tests for scheduler configuration."""

    def test_entity_change_threshold(self):
        """Test entity change threshold is 10%."""
        from modules.scheduler.jobs import CommunityDetectionScheduler

        assert CommunityDetectionScheduler.ENTITY_CHANGE_THRESHOLD == 0.10

    def test_rebuild_interval_days(self):
        """Test rebuild interval is 7 days."""
        from modules.scheduler.jobs import CommunityDetectionScheduler

        assert CommunityDetectionScheduler.REBUILD_INTERVAL_DAYS == 7

    def test_redis_keys(self):
        """Test Redis key names."""
        from modules.scheduler.jobs import CommunityDetectionScheduler

        assert CommunityDetectionScheduler.LAST_REBUILD_KEY == "community:last_rebuild"
        assert CommunityDetectionScheduler.ENTITY_COUNT_KEY == "community:entity_count"
