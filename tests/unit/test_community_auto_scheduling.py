# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for IncrementalCommunityUpdater.check_and_run() and force_rebuild()."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.graph_store.incremental_community_updater import (
    IncrementalCommunityUpdater,
    IncrementalUpdateResult,
)


@pytest.fixture
def mock_pool():
    """Mock Neo4j pool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock()
    return pool


@pytest.fixture
def updater(mock_pool):
    """Create updater instance."""
    return IncrementalCommunityUpdater(pool=mock_pool)


def _make_rebuild_result(communities=5, entities=100, modularity=0.45):
    """Create a mock CommunityDetectionResult."""
    return MagicMock(
        total_communities=communities,
        total_entities=entities,
        modularity=modularity,
    )


class TestCheckAndRun:
    """Tests for check_and_run() trigger conditions."""

    @pytest.mark.asyncio
    async def test_triggers_when_no_communities_exist(self, updater, mock_pool):
        """No communities → full rebuild triggered with reason='no_communities_exist'."""
        mock_pool.execute_query.side_effect = [
            [{"total": 0}],  # _get_community_count
            None,  # _calculate_modularity (before, in run_full_rebuild)
            None,  # _update_full_rebuild_metadata (also calls _calculate_modularity internally)
            None,  # _update_full_rebuild_metadata execute
        ]

        with patch("modules.graph_store.community_detector.CommunityDetector") as MockDetector:
            mock_detector = MagicMock()
            mock_detector.rebuild_communities = AsyncMock(return_value=_make_rebuild_result())
            MockDetector.return_value = mock_detector

            result = await updater.check_and_run()

        assert result["triggered"] is True
        assert result["reason"] == "no_communities_exist"
        assert result["communities_created"] == 5

    @pytest.mark.asyncio
    async def test_triggers_on_entity_change_exceeded(self, updater, mock_pool):
        """Entity count change > 10% → rebuild with reason='entity_change_exceeded'."""
        mock_pool.execute_query.side_effect = [
            [{"total": 5}],  # _get_community_count → communities exist
            [{"total": 120}],  # _check_entity_change → current count = 120
            [{"previous_count": 100}],  # _check_entity_change → previous = 100 (20% change)
            None,  # _calculate_modularity (before, in run_full_rebuild)
            None,  # _update_full_rebuild_metadata
        ]

        with patch("modules.graph_store.community_detector.CommunityDetector") as MockDetector:
            mock_detector = MagicMock()
            mock_detector.rebuild_communities = AsyncMock(
                return_value=_make_rebuild_result(8, 120, 0.50)
            )
            MockDetector.return_value = mock_detector

            result = await updater.check_and_run()

        assert result["triggered"] is True
        assert result["reason"] == "entity_change_exceeded"
        assert result["current_entity_count"] == 120
        assert result["previous_entity_count"] == 100

    @pytest.mark.asyncio
    async def test_triggers_on_rebuild_interval_exceeded(self, updater, mock_pool):
        """Last rebuild > 7 days → rebuild with reason='rebuild_interval_exceeded'."""
        old_date = datetime.now(UTC) - timedelta(days=8)

        mock_pool.execute_query.side_effect = [
            [{"total": 5}],  # _get_community_count → communities exist
            [{"total": 100}],  # _check_entity_change → current count = 100
            [{"previous_count": 98}],  # _check_entity_change → previous = 98 (2% change)
            # check_full_rebuild_needed → get_stats
            [
                {
                    "last_full_rebuild": old_date,
                    "last_incremental": datetime.now(UTC),
                    "pending_count": 5,
                }
            ],
            [{"total": 5}],  # get_stats → total_communities
            None,  # _calculate_modularity (before, in run_full_rebuild)
            None,  # _update_full_rebuild_metadata
        ]

        with patch("modules.graph_store.community_detector.CommunityDetector") as MockDetector:
            mock_detector = MagicMock()
            mock_detector.rebuild_communities = AsyncMock(
                return_value=_make_rebuild_result(6, 100, 0.42)
            )
            MockDetector.return_value = mock_detector

            result = await updater.check_and_run()

        assert result["triggered"] is True
        assert result["reason"] == "rebuild_interval_exceeded"

    @pytest.mark.asyncio
    async def test_no_trigger_when_conditions_not_met(self, updater, mock_pool):
        """Communities exist, entity change < 10%, recent rebuild → no trigger."""
        recent_date = datetime.now(UTC) - timedelta(hours=1)

        mock_pool.execute_query.side_effect = [
            [{"total": 5}],  # _get_community_count → communities exist
            [{"total": 100}],  # _check_entity_change → current count = 100
            [{"previous_count": 98}],  # _check_entity_change → previous = 98 (2% change)
            # check_full_rebuild_needed → get_stats
            [
                {
                    "last_full_rebuild": recent_date,
                    "last_incremental": recent_date,
                    "pending_count": 5,
                }
            ],
            [{"total": 5}],  # get_stats → total_communities
        ]

        result = await updater.check_and_run()

        assert result["triggered"] is False
        assert result["reason"] is None


class TestForceRebuild:
    """Tests for force_rebuild()."""

    @pytest.mark.asyncio
    async def test_force_rebuild_always_triggers(self, updater, mock_pool):
        """force_rebuild() unconditionally runs Leiden rebuild."""
        mock_pool.execute_query.side_effect = [
            None,  # _calculate_modularity (before)
            None,  # _update_full_rebuild_metadata
        ]

        with patch("modules.graph_store.community_detector.CommunityDetector") as MockDetector:
            mock_detector = MagicMock()
            mock_detector.rebuild_communities = AsyncMock(
                return_value=_make_rebuild_result(12, 200, 0.48)
            )
            MockDetector.return_value = mock_detector

            result = await updater.force_rebuild()

        assert result["triggered"] is True
        assert result["reason"] == "forced"
        assert result["communities_created"] == 12

    @pytest.mark.asyncio
    async def test_force_rebuild_returns_modularity(self, updater, mock_pool):
        """force_rebuild() returns modularity from the detection result."""
        mock_pool.execute_query.side_effect = [
            None,  # _calculate_modularity (before)
            None,  # _update_full_rebuild_metadata
        ]

        with patch("modules.graph_store.community_detector.CommunityDetector") as MockDetector:
            mock_detector = MagicMock()
            mock_detector.rebuild_communities = AsyncMock(
                return_value=_make_rebuild_result(10, 150, 0.55)
            )
            MockDetector.return_value = mock_detector

            result = await updater.force_rebuild()

        assert result["triggered"] is True
        assert result["modularity"] == 0.55


class TestStateUpdate:
    """Tests for metadata state updates after rebuild."""

    @pytest.mark.asyncio
    async def test_metadata_updated_after_rebuild(self, updater, mock_pool):
        """_update_full_rebuild_metadata() stores entity_count."""
        mock_pool.execute_query.return_value = None

        await updater._update_full_rebuild_metadata()

        # _calculate_modularity + MERGE query = 2 calls
        assert mock_pool.execute_query.call_count == 2
        # Last call should be the MERGE query with entity_count
        last_call = mock_pool.execute_query.call_args_list[-1]
        query = last_call[0][0] if last_call[0] else ""
        assert "entity_count" in query
        assert "last_full_rebuild_at" in query


class TestClassConstants:
    """Tests for class-level constants."""

    def test_entity_change_threshold(self):
        assert IncrementalCommunityUpdater.ENTITY_CHANGE_THRESHOLD == 0.10

    def test_rebuild_interval_days(self):
        assert IncrementalCommunityUpdater.REBUILD_INTERVAL_DAYS == 7

    def test_last_rebuild_key(self):
        assert IncrementalCommunityUpdater.LAST_REBUILD_KEY == "community:last_rebuild"

    def test_entity_count_key(self):
        assert IncrementalCommunityUpdater.ENTITY_COUNT_KEY == "community:entity_count"


class TestEntityChangeDetection:
    """Tests for _check_entity_change() edge cases."""

    @pytest.mark.asyncio
    async def test_no_previous_count(self, updater, mock_pool):
        """No previous entity count → no trigger (first run after migration)."""
        mock_pool.execute_query.side_effect = [
            [{"total": 100}],  # current count
            [{}],  # no previous_count field
        ]

        exceeded, current, previous = await updater._check_entity_change()

        assert exceeded is False
        assert current == 100
        assert previous == 0

    @pytest.mark.asyncio
    async def test_zero_previous_count(self, updater, mock_pool):
        """Zero previous count → no trigger (avoid division by zero)."""
        mock_pool.execute_query.side_effect = [
            [{"total": 100}],  # current count
            [{"previous_count": 0}],  # previous = 0
        ]

        exceeded, current, previous = await updater._check_entity_change()

        assert exceeded is False
        assert current == 100
        assert previous == 0

    @pytest.mark.asyncio
    async def test_exactly_at_threshold(self, updater, mock_pool):
        """Change exactly at 10% → no trigger (must exceed, not meet)."""
        mock_pool.execute_query.side_effect = [
            [{"total": 110}],  # current = 110
            [{"previous_count": 100}],  # previous = 100 → 10% exactly
        ]

        exceeded, _, _ = await updater._check_entity_change()
        assert exceeded is False

    @pytest.mark.asyncio
    async def test_just_above_threshold(self, updater, mock_pool):
        """Change just above 10% → trigger."""
        mock_pool.execute_query.side_effect = [
            [{"total": 112}],  # current = 112
            [{"previous_count": 100}],  # previous = 100 → 12%
        ]

        exceeded, current, previous = await updater._check_entity_change()
        assert exceeded is True
        assert current == 112
        assert previous == 100
