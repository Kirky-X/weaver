# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for BriefingEngine."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.briefing.engine import BriefingEngine


class TestBriefingEngine:
    """Tests for BriefingEngine."""

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
    def engine(self, mock_pool):
        """Create a BriefingEngine instance."""
        return BriefingEngine(pool=mock_pool)

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


class TestBriefingEngineWithArticles:
    """Tests for BriefingEngine with mock articles."""

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
    def engine(self, mock_pool):
        """Create a BriefingEngine with mocked fetch."""
        engine = BriefingEngine(pool=mock_pool)
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


class TestBriefingEnginePersist:
    """Tests for BriefingEngine._persist."""

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
    def engine(self, mock_pool):
        """Create a BriefingEngine instance."""
        return BriefingEngine(pool=mock_pool)

    @pytest.mark.asyncio
    async def test_persist_adds_briefing_and_items(self, engine, mock_pool):
        """Test _persist adds DailyBriefing and DailyBriefingItem records."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
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
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = MagicMock()
        mock_session.execute.return_value = mock_result

        result = await engine._persist(date(2026, 6, 1), [])
        assert result == 0

    @pytest.mark.asyncio
    async def test_persist_returns_zero_on_error(self, engine, mock_pool):
        """Test _persist returns 0 on database error."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_session.execute.side_effect = Exception("DB error")
        result = await engine._persist(date(2026, 6, 1), [])
        assert result == 0


class TestBriefingEngineFetchArticles:
    """Tests for BriefingEngine._fetch_articles."""

    @pytest.mark.asyncio
    async def test_fetch_articles_returns_empty_list(self):
        """Test _fetch_articles returns empty list."""
        engine = BriefingEngine(pool=MagicMock())
        result = await engine._fetch_articles(date(2026, 6, 1))
        assert result == []
