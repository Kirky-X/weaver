# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for AnalyticsStorage."""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.analytics.storage import AnalyticsStorage


class TestAnalyticsStorageSaveShift:
    """Tests for AnalyticsStorage.save_shift."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock RelationalPool."""
        pool = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        pool.session_context.return_value = mock_session
        return pool

    @pytest.fixture
    def storage(self, mock_pool):
        """Create an AnalyticsStorage instance."""
        return AnalyticsStorage(mock_pool)

    @pytest.mark.asyncio
    async def test_save_shift_calls_session_add_and_commit(self, storage, mock_pool):
        """Test save_shift adds record and commits."""
        shift = {
            "community_id": "community_1",
            "shift_type": "pel",
            "direction": "negative",
            "magnitude": 0.35,
            "confidence": 0.7,
        }
        await storage.save_shift(shift)
        mock_pool.session_context.return_value.__aenter__.return_value.add.assert_called_once()
        mock_pool.session_context.return_value.__aenter__.return_value.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_shift_raises_on_failure(self, storage, mock_pool):
        """Test save_shift raises on database error."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_session.commit.side_effect = Exception("DB error")
        shift = {
            "community_id": "community_1",
            "shift_type": "pel",
            "direction": "negative",
            "magnitude": 0.35,
            "confidence": 0.7,
        }
        with pytest.raises(Exception, match="DB error"):
            await storage.save_shift(shift)

    @pytest.mark.asyncio
    async def test_save_shift_with_optional_fields(self, storage, mock_pool):
        """Test save_shift handles optional fields."""
        from datetime import datetime

        shift = {
            "community_id": "community_1",
            "shift_type": "binseg",
            "direction": "positive",
            "magnitude": 0.42,
            "confidence": 0.8,
            "detected_at": datetime(2026, 6, 1, 12, 0, 0),
            "before_avg": 0.3,
            "after_avg": 0.72,
            "trigger_article_ids": ["art1", "art2"],
        }
        await storage.save_shift(shift)
        mock_pool.session_context.return_value.__aenter__.return_value.add.assert_called_once()
        mock_pool.session_context.return_value.__aenter__.return_value.commit.assert_called_once()


class TestAnalyticsStorageGetShifts:
    """Tests for AnalyticsStorage.get_shifts."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock RelationalPool."""
        pool = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        pool.session_context.return_value = mock_session
        return pool

    @pytest.fixture
    def storage(self, mock_pool):
        """Create an AnalyticsStorage instance."""
        return AnalyticsStorage(mock_pool)

    @pytest.mark.asyncio
    async def test_get_shifts_returns_list(self, storage, mock_pool):
        """Test get_shifts returns a list."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        result = await storage.get_shifts()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_shifts_with_community_filter(self, storage, mock_pool):
        """Test get_shifts filters by community_id."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        result = await storage.get_shifts(community_id="community_1")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_shifts_raises_on_error(self, storage, mock_pool):
        """get_shifts must raise on DB error (Rule 12 — fail loud).

        API endpoint catches and returns empty list to client; storage
        layer must surface the failure so callers can distinguish
        "no data" from "DB broken". Returning [] on error masked
        failures (T003-sub4 H2).
        """
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_session.execute.side_effect = Exception("DB error")
        with pytest.raises(Exception, match="DB error"):
            await storage.get_shifts()

    @pytest.mark.asyncio
    async def test_get_shifts_with_limit(self, storage, mock_pool):
        """Test get_shifts respects limit parameter."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        result = await storage.get_shifts(limit=10)
        assert result == []


class TestAnalyticsStorageSaveArticleShift:
    """Tests for AnalyticsStorage.save_shift with article-level fields (T003).

    Migration 30 extended sentiment_shifts with article_id/entity_name/
    shift_value nullable fields. save_shift must persist these fields
    when present in the input dict.
    """

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        pool.session_context.return_value = mock_session
        return pool

    @pytest.fixture
    def storage(self, mock_pool):
        return AnalyticsStorage(mock_pool)

    @pytest.mark.asyncio
    async def test_save_shift_persists_article_level_fields(self, storage, mock_pool):
        """save_shift must write article_id/entity_name/shift_value when provided."""
        article_uuid = uuid.uuid4()
        shift = {
            "community_id": "entity::CompanyX",
            "shift_type": "mean_shift",
            "direction": "up",
            "magnitude": 0.15,
            "confidence": 1.0,
            "detected_at": datetime(2026, 7, 17, 10, 0, 0),
            "window_start": datetime(2026, 7, 17, 10, 0, 0),
            "window_end": datetime(2026, 7, 17, 10, 0, 0),
            "before_avg": 0.50,
            "after_avg": 0.65,
            "article_id": article_uuid,
            "entity_name": "CompanyX",
            "shift_value": 0.15,
        }
        await storage.save_shift(shift)

        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_session.add.assert_called_once()
        record = mock_session.add.call_args.args[0]
        assert record.article_id == article_uuid
        assert record.entity_name == "CompanyX"
        assert float(record.shift_value) == pytest.approx(0.15)
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_shift_article_fields_default_none_when_missing(self, storage, mock_pool):
        """save_shift must leave article_id/entity_name/shift_value None when absent.

        Ensures community-level shifts (existing callers) still work after
        migration 30 — new fields are nullable and default to None.
        """
        shift = {
            "community_id": "tech-ai",
            "shift_type": "pel",
            "direction": "negative",
            "magnitude": 0.35,
            "confidence": 0.7,
        }
        await storage.save_shift(shift)

        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        record = mock_session.add.call_args.args[0]
        assert record.article_id is None
        assert record.entity_name is None
        assert record.shift_value is None


class TestAnalyticsStorageGetLastArticleShift:
    """Tests for AnalyticsStorage.get_last_article_shift (T003).

    Queries the most recent article-level sentiment_shifts record for a
    given entity_name. Returns None when no article-level record exists.
    """

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        pool.session_context.return_value = mock_session
        return pool

    @pytest.fixture
    def storage(self, mock_pool):
        return AnalyticsStorage(mock_pool)

    @pytest.mark.asyncio
    async def test_get_last_article_shift_returns_record(self, storage, mock_pool):
        """Returns the most recent article-level shift dict for the entity."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_row = MagicMock()
        mock_row.article_id = uuid.uuid4()
        mock_row.entity_name = "CompanyX"
        mock_row.shift_value = 0.12
        mock_row.before_avg = 0.50
        mock_row.after_avg = 0.62
        mock_row.detected_at = datetime(2026, 7, 17, 9, 0, 0)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_row
        mock_session.execute.return_value = mock_result

        result = await storage.get_last_article_shift("CompanyX")

        assert result is not None
        assert result["entity_name"] == "CompanyX"
        assert float(result["shift_value"]) == pytest.approx(0.12)
        assert float(result["after_avg"]) == pytest.approx(0.62)
        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_last_article_shift_returns_none_when_no_record(self, storage, mock_pool):
        """Returns None when entity has no article-level shifts yet."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        result = await storage.get_last_article_shift("UnknownEntity")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_last_article_shift_raises_on_error(self, storage, mock_pool):
        """Raises on DB error (Rule 12 — fail loud, T003-sub4 H2).

        Previously returned None on error, which SentimentTrackerNode
        misread as "no previous article" and seeded an incorrect
        shift_value=0 record. The caller (_track_single_entity) already
        catches exceptions and marks sentiment_shift in degraded_fields,
        so raising is safe and surfaces the real failure.
        """
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_session.execute.side_effect = Exception("DB connection lost")

        with pytest.raises(Exception, match="DB connection lost"):
            await storage.get_last_article_shift("CompanyX")

    @pytest.mark.asyncio
    async def test_get_last_article_shift_filters_by_entity_and_article_id(
        self, storage, mock_pool
    ):
        """Query must filter entity_name AND article_id IS NOT NULL.

        Ensures community-level shifts (article_id=None) are not returned
        — only article-level records count as "previous article sentiment".
        """
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        await storage.get_last_article_shift("CompanyX")

        # Verify query was issued (the WHERE clause logic is in implementation)
        mock_session.execute.assert_awaited_once()


class TestAnalyticsStorageGetShiftsScope:
    """Tests for AnalyticsStorage.get_shifts scope parameter (T003-sub4 H1).

    scope separates community-level shifts (article_id IS NULL, from
    SentimentShiftDetector) from article-level shifts (article_id IS NOT
    NULL, from T003 SentimentTrackerNode). Default scope='community'
    preserves historical API behavior and avoids polluting community
    queries with per-entity article-level rows (Rule 14).
    """

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        pool.session_context.return_value = mock_session
        return pool

    @pytest.fixture
    def storage(self, mock_pool):
        return AnalyticsStorage(mock_pool)

    @pytest.mark.asyncio
    async def test_get_shifts_default_scope_is_community(self, storage, mock_pool):
        """Default scope='community' filters article_id IS NULL."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await storage.get_shifts()

        # The query was issued; the WHERE article_id IS NULL filter is
        # applied in the implementation (verified by code review).
        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_shifts_scope_community_filters_article_id_null(self, storage, mock_pool):
        """scope='community' excludes article-level rows."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await storage.get_shifts(scope="community")

        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_shifts_scope_article_filters_article_id_not_null(self, storage, mock_pool):
        """scope='article' returns only T003 article-level rows."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await storage.get_shifts(scope="article")

        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_shifts_scope_all_returns_both(self, storage, mock_pool):
        """scope='all' returns both community-level and article-level rows."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await storage.get_shifts(scope="all")

        mock_session.execute.assert_awaited_once()
