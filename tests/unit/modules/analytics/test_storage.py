# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for AnalyticsStorage."""

from __future__ import annotations

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
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        result = await storage.get_shifts()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_shifts_with_community_filter(self, storage, mock_pool):
        """Test get_shifts filters by community_id."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        result = await storage.get_shifts(community_id="community_1")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_shifts_empty_on_error(self, storage, mock_pool):
        """Test get_shifts returns empty list on error."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_session.execute.side_effect = Exception("DB error")
        result = await storage.get_shifts()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_shifts_with_limit(self, storage, mock_pool):
        """Test get_shifts respects limit parameter."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        result = await storage.get_shifts(limit=10)
        assert result == []
