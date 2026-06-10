# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for ForgettingScheduler.

Tests for:
- Marking events stale after 90 days unaccessed
- Archiving stale events
- Preserving high-importance events from archival
- Data retention policy: hot(1yr) → warm → cold(7yr)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from modules.memory.evolution.forgetting_scheduler import ForgettingScheduler


class TestMarkStaleEvents90Days:
    """Tests for marking events as stale after 90 days."""

    @pytest.fixture
    def scheduler(self):
        return ForgettingScheduler()

    def test_mark_stale_events_90_days(self, scheduler):
        """Events not accessed in 90+ days should be marked stale."""
        now = datetime.now(UTC)
        events = [
            {
                "id": "e1",
                "last_accessed": (now - timedelta(days=100)).isoformat(),
                "importance": 0.5,
            },
            {
                "id": "e2",
                "last_accessed": (now - timedelta(days=30)).isoformat(),
                "importance": 0.5,
            },
        ]

        result = scheduler.mark_stale_events(events)

        stale_ids = [e["id"] for e in result if e.get("stale")]
        assert "e1" in stale_ids
        assert "e2" not in stale_ids

    def test_mark_stale_exactly_90_days(self, scheduler):
        """Events accessed exactly 90 days ago should be marked stale."""
        now = datetime.now(UTC)
        events = [
            {
                "id": "e1",
                "last_accessed": (now - timedelta(days=90)).isoformat(),
                "importance": 0.5,
            },
        ]

        result = scheduler.mark_stale_events(events)

        assert result[0]["stale"] is True

    def test_mark_stale_recent_events_not_stale(self, scheduler):
        """Events accessed within 90 days should not be marked stale."""
        now = datetime.now(UTC)
        events = [
            {
                "id": "e1",
                "last_accessed": (now - timedelta(days=10)).isoformat(),
                "importance": 0.5,
            },
        ]

        result = scheduler.mark_stale_events(events)

        assert result[0].get("stale", False) is False

    def test_mark_stale_empty_list(self, scheduler):
        """Empty event list should return empty list."""
        result = scheduler.mark_stale_events([])

        assert result == []

    def test_mark_stale_no_last_accessed(self, scheduler):
        """Events without last_accessed should not be marked stale."""
        events = [
            {"id": "e1", "importance": 0.5},
        ]

        result = scheduler.mark_stale_events(events)

        assert result[0].get("stale", False) is False


class TestArchiveStaleEvents:
    """Tests for archiving stale events."""

    @pytest.fixture
    def scheduler(self):
        return ForgettingScheduler()

    def test_archive_stale_events(self, scheduler):
        """Stale events should be archived."""
        events = [
            {"id": "e1", "stale": True, "importance": 0.5},
            {"id": "e2", "stale": False, "importance": 0.5},
        ]

        result = scheduler.archive_stale_events(events)

        archived_ids = [e["id"] for e in result if e.get("archived")]
        assert "e1" in archived_ids
        assert "e2" not in archived_ids

    def test_archive_non_stale_events_not_archived(self, scheduler):
        """Non-stale events should not be archived."""
        events = [
            {"id": "e1", "stale": False, "importance": 0.5},
        ]

        result = scheduler.archive_stale_events(events)

        assert result[0].get("archived", False) is False

    def test_archive_empty_list(self, scheduler):
        """Empty event list should return empty list."""
        result = scheduler.archive_stale_events([])

        assert result == []


class TestPreserveHighImportanceEvents:
    """Tests for preserving high-importance events from archival."""

    @pytest.fixture
    def scheduler(self):
        return ForgettingScheduler()

    def test_preserve_high_importance_events(self, scheduler):
        """High-importance events should not be archived even if stale."""
        events = [
            {"id": "e1", "stale": True, "importance": 0.9},
            {"id": "e2", "stale": True, "importance": 0.5},
        ]

        result = scheduler.archive_stale_events(events)

        archived_ids = [e["id"] for e in result if e.get("archived")]
        assert "e1" not in archived_ids  # High importance, preserved
        assert "e2" in archived_ids  # Low importance, archived

    def test_preserve_threshold_boundary(self, scheduler):
        """Events at exactly the importance threshold should be preserved."""
        events = [
            {
                "id": "e1",
                "stale": True,
                "importance": ForgettingScheduler.IMPORTANCE_PRESERVE_THRESHOLD,
            },
        ]

        result = scheduler.archive_stale_events(events)

        assert result[0].get("archived", False) is False

    def test_preserve_below_threshold_archived(self, scheduler):
        """Events just below the importance threshold should be archived."""
        events = [
            {
                "id": "e1",
                "stale": True,
                "importance": ForgettingScheduler.IMPORTANCE_PRESERVE_THRESHOLD - 0.01,
            },
        ]

        result = scheduler.archive_stale_events(events)

        assert result[0].get("archived", False) is True


class TestDataRetentionPolicy:
    """Tests for data retention policy: hot(1yr) → warm → cold(7yr)."""

    @pytest.fixture
    def scheduler(self):
        return ForgettingScheduler()

    def test_data_retention_hot_within_1_year(self, scheduler):
        """Events within 1 year should be classified as 'hot'."""
        now = datetime.now(UTC)
        event = {
            "id": "e1",
            "created_at": (now - timedelta(days=180)).isoformat(),
        }

        tier = scheduler.apply_retention_policy(event)

        assert tier == "hot"

    def test_data_retention_warm_1_to_3_years(self, scheduler):
        """Events between 1-3 years should be classified as 'warm'."""
        now = datetime.now(UTC)
        event = {
            "id": "e1",
            "created_at": (now - timedelta(days=500)).isoformat(),
        }

        tier = scheduler.apply_retention_policy(event)

        assert tier == "warm"

    def test_data_retention_cold_3_to_7_years(self, scheduler):
        """Events between 3-7 years should be classified as 'cold'."""
        now = datetime.now(UTC)
        event = {
            "id": "e1",
            "created_at": (now - timedelta(days=4 * 365)).isoformat(),
        }

        tier = scheduler.apply_retention_policy(event)

        assert tier == "cold"

    def test_data_retention_expired_over_7_years(self, scheduler):
        """Events over 7 years should be classified as 'expired'."""
        now = datetime.now(UTC)
        event = {
            "id": "e1",
            "created_at": (now - timedelta(days=8 * 365)).isoformat(),
        }

        tier = scheduler.apply_retention_policy(event)

        assert tier == "expired"

    def test_data_retention_exactly_1_year(self, scheduler):
        """Events exactly at 1 year boundary should be 'warm'."""
        now = datetime.now(UTC)
        event = {
            "id": "e1",
            "created_at": (now - timedelta(days=365)).isoformat(),
        }

        tier = scheduler.apply_retention_policy(event)

        assert tier == "warm"

    def test_data_retention_exactly_3_years(self, scheduler):
        """Events exactly at 3 year boundary should be 'cold'."""
        now = datetime.now(UTC)
        event = {
            "id": "e1",
            "created_at": (now - timedelta(days=3 * 365)).isoformat(),
        }

        tier = scheduler.apply_retention_policy(event)

        assert tier == "cold"

    def test_data_retention_exactly_7_years(self, scheduler):
        """Events exactly at 7 year boundary should be 'expired'."""
        now = datetime.now(UTC)
        event = {
            "id": "e1",
            "created_at": (now - timedelta(days=7 * 365)).isoformat(),
        }

        tier = scheduler.apply_retention_policy(event)

        assert tier == "expired"

    def test_data_retention_no_created_at(self, scheduler):
        """Events without created_at should default to 'hot'."""
        event = {"id": "e1"}

        tier = scheduler.apply_retention_policy(event)

        assert tier == "hot"
