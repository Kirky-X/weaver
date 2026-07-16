# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for DailyBriefingEngine."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.briefing.engine import DailyBriefingEngine
from tests.helpers import create_mock_relational_pool


class TestDailyBriefingEngine:
    """Tests for DailyBriefingEngine."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock RelationalPool."""
        pool = create_mock_relational_pool()
        pool.session_context = pool.session
        return pool

    @pytest.fixture
    def engine(self, mock_pool):
        """Create a DailyBriefingEngine instance."""
        return DailyBriefingEngine(pool=mock_pool)

    @pytest.mark.asyncio
    async def test_generate_returns_dict(self, engine):
        """Test generate returns a dict."""
        result = await engine.generate()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_generate_empty_when_no_articles(self, engine):
        """Test generate returns empty items when no articles."""
        result = await engine.generate(date(2026, 6, 1))
        assert result["items"] == []
        assert result["briefing_date"] == date(2026, 6, 1)

    @pytest.mark.asyncio
    async def test_generate_with_date(self, engine):
        """Test generate accepts a specific date."""
        result = await engine.generate(date(2026, 6, 15))
        assert result["briefing_date"] == date(2026, 6, 15)

    @pytest.mark.asyncio
    async def test_generate_uses_today_by_default(self, engine):
        """Test generate uses today when no date given."""
        result = await engine.generate()
        assert result["briefing_date"] == date.today()


class TestDailyBriefingEngineWithArticles:
    """Tests for DailyBriefingEngine with mock articles."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock RelationalPool."""
        pool = create_mock_relational_pool()
        pool.session_context = pool.session
        return pool

    @pytest.fixture
    def engine(self, mock_pool):
        """Create a DailyBriefingEngine with mocked fetch."""
        engine = DailyBriefingEngine(pool=mock_pool)
        return engine

    @pytest.mark.asyncio
    async def test_generate_scores_articles(self, engine):
        """Test generate scores articles before selection."""
        articles = [
            {
                "article_id": "1",
                "category": "tech",
                "score": 0.9,
                "credibility_score": 0.8,
                "quality_score": 0.8,
            },
            {
                "article_id": "2",
                "category": "sports",
                "score": 0.7,
                "credibility_score": 0.6,
                "quality_score": 0.6,
            },
        ]
        with patch.object(engine, "_fetch_articles", return_value=articles):
            with patch.object(engine, "_persist", return_value=1):
                result = await engine.generate(date(2026, 6, 1))
                assert len(result["items"]) == 2

    @pytest.mark.asyncio
    async def test_generate_sorts_by_score(self, engine):
        """Test generate sorts articles by score descending."""
        articles = [
            {
                "article_id": "1",
                "category": "tech",
                "score": 0.3,
                "credibility_score": 0.5,
                "quality_score": 0.5,
            },
            {
                "article_id": "2",
                "category": "sports",
                "score": 0.9,
                "credibility_score": 0.5,
                "quality_score": 0.5,
            },
        ]
        with patch.object(engine, "_fetch_articles", return_value=articles):
            with patch.object(engine, "_persist", return_value=1):
                result = await engine.generate(date(2026, 6, 1))
                assert result["items"][0]["article_id"] == "2"
                assert result["items"][1]["article_id"] == "1"

    @pytest.mark.asyncio
    async def test_generate_respects_persist_result(self, engine):
        """Test generate returns the briefing id from persist."""
        articles = [
            {
                "article_id": "1",
                "category": "tech",
                "score": 0.9,
                "credibility_score": 0.8,
                "quality_score": 0.8,
            },
        ]
        with patch.object(engine, "_fetch_articles", return_value=articles):
            with patch.object(engine, "_persist", return_value=42):
                result = await engine.generate(date(2026, 6, 1))
                assert result["id"] == 42

    @pytest.mark.asyncio
    async def test_generate_stores_score_breakdown(self, engine):
        """Test generate stores score_breakdown in each item."""
        articles = [
            {
                "article_id": "1",
                "category": "tech",
                "score": 0.9,
                "credibility_score": 0.8,
                "quality_score": 0.8,
            },
        ]
        with patch.object(engine, "_fetch_articles", return_value=articles):
            with patch.object(engine, "_persist", return_value=1) as mock_persist:
                result = await engine.generate(date(2026, 6, 1))
                # Verify _persist was called with items containing score_breakdown
                call_args = mock_persist.call_args
                items = call_args[0][1]  # second positional arg
                assert len(items) == 1
                assert "score_breakdown" in items[0]
                breakdown = items[0]["score_breakdown"]
                assert "quality" in breakdown
                assert "cross_reference" in breakdown
                assert "novelty" in breakdown
                assert "user_preference" in breakdown
                assert "composite" in breakdown

    @pytest.mark.asyncio
    async def test_generate_items_include_score_breakdown(self, engine):
        """Test generate result items include score_breakdown."""
        articles = [
            {
                "article_id": "1",
                "category": "tech",
                "score": 0.9,
                "credibility_score": 0.8,
                "quality_score": 0.8,
            },
        ]
        with patch.object(engine, "_fetch_articles", return_value=articles):
            with patch.object(engine, "_persist", return_value=1):
                result = await engine.generate(date(2026, 6, 1))
                item = result["items"][0]
                assert "score_breakdown" in item
                assert isinstance(item["score_breakdown"], dict)


class TestDailyBriefingEnginePersist:
    """Tests for DailyBriefingEngine._persist."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock RelationalPool."""
        pool = create_mock_relational_pool()
        pool.session_context = pool.session
        return pool

    @pytest.fixture
    def engine(self, mock_pool):
        """Create a DailyBriefingEngine instance."""
        return DailyBriefingEngine(pool=mock_pool)

    @pytest.mark.asyncio
    async def test_persist_adds_briefing_and_items(self, engine, mock_pool):
        """Test _persist adds DailyBriefing and DailyBriefingItem records."""
        mock_session = mock_pool.session.return_value
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        items = [
            {"article_id": "art1", "category": "tech", "reason": "Breaking"},
            {"article_id": "art2", "category": "sports", "reason": "Update"},
        ]
        result = await engine._persist(date(2026, 6, 1), items)
        assert result is None  # mock session has no .id set
        assert mock_session.add.call_count >= 1
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_returns_zero_on_existing(self, engine, mock_pool):
        """Test _persist returns 0 if briefing already exists."""
        mock_session = mock_pool.session.return_value
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = MagicMock()
        mock_session.execute.return_value = mock_result

        result = await engine._persist(date(2026, 6, 1), [])
        assert result == 0

    @pytest.mark.asyncio
    async def test_persist_returns_zero_on_error(self, engine, mock_pool):
        """Test _persist returns 0 on database error."""
        mock_session = mock_pool.session.return_value
        mock_session.execute.side_effect = Exception("DB error")
        result = await engine._persist(date(2026, 6, 1), [])
        assert result == 0

    @pytest.mark.asyncio
    async def test_persist_stores_score_breakdown_in_items(self, engine, mock_pool):
        """Test _persist stores score_breakdown JSONB in DailyBriefingItem."""
        mock_session = mock_pool.session.return_value
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        items = [
            {
                "article_id": "art1",
                "category": "tech",
                "score": 0.85,
                "score_breakdown": {
                    "quality": 0.8,
                    "cross_reference": 0.7,
                    "novelty": 0.9,
                    "user_preference": 0.6,
                    "composite": 0.85,
                },
            },
        ]
        await engine._persist(date(2026, 6, 1), items)
        # Verify the DailyBriefingItem was added with score_breakdown
        add_calls = mock_session.add.call_args_list
        # Find the DailyBriefingItem add call (not the DailyBriefing one)
        item_added = False
        for call in add_calls:
            obj = call[0][0]
            if hasattr(obj, "score_breakdown"):
                assert obj.score_breakdown == items[0]["score_breakdown"]
                item_added = True
        assert item_added


class TestDailyBriefingEngineFetchArticles:
    """Tests for DailyBriefingEngine._fetch_articles."""

    @pytest.mark.asyncio
    async def test_fetch_articles_returns_empty_list(self):
        """Test _fetch_articles returns empty list."""
        engine = DailyBriefingEngine(pool=MagicMock())
        result = await engine._fetch_articles(date(2026, 6, 1))
        assert result == []


class TestDailyBriefingEngineFetchArticlesWithPool:
    """Tests for DailyBriefingEngine._fetch_articles with database pool."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock RelationalPool."""
        pool = create_mock_relational_pool()
        pool.session_context = pool.session
        return pool

    @pytest.fixture
    def engine(self, mock_pool):
        """Create a DailyBriefingEngine with mock pool."""
        return DailyBriefingEngine(pool=mock_pool)

    @pytest.mark.asyncio
    async def test_fetch_articles_returns_recent_24h(self, engine, mock_pool):
        """Test _fetch_articles queries last 24 hours of articles."""
        mock_row1 = MagicMock()
        mock_row1.id = "art-1"
        mock_row1.title = "Article 1"
        mock_row1.category = "tech"
        mock_row1.score = 0.9
        mock_row1.credibility_score = 0.8
        mock_row1.quality_score = 0.7

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_row1]

        mock_session = mock_pool.session.return_value
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await engine._fetch_articles(date(2026, 6, 1))

        mock_session.execute.assert_called_once()
        assert len(result) == 1
        assert result[0]["article_id"] == "art-1"

    @pytest.mark.asyncio
    async def test_generate_produces_briefing(self, engine, mock_pool):
        """Test generate produces a complete briefing."""
        articles = [
            {
                "article_id": "art-1",
                "category": "tech",
                "score": 0.9,
                "credibility_score": 0.8,
                "quality_score": 0.7,
            },
        ]

        with (
            patch.object(engine, "_fetch_articles", return_value=articles),
            patch.object(engine, "_persist", return_value=1),
        ):
            result = await engine.generate(date(2026, 6, 1))

        assert result["briefing_date"] == date(2026, 6, 1)
        assert len(result["items"]) == 1
        assert result["id"] == 1


class TestDailyBriefingEngineClassRename:
    """Tests verifying class has been renamed to DailyBriefingEngine."""

    def test_class_name_is_daily_briefing_engine(self):
        """Test the class is named DailyBriefingEngine."""
        from modules.briefing.engine import DailyBriefingEngine

        assert DailyBriefingEngine.__name__ == "DailyBriefingEngine"
