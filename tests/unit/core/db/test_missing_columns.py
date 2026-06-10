# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for missing database columns (Task 6).

Tests verify that all missing columns specified in the design document
have been added to the respective ORM models.
"""

from __future__ import annotations

from sqlalchemy import inspect


class TestCommunityVectorMissingColumns:
    """Tests for missing columns on community_vectors table."""

    def test_community_vectors_has_title(self):
        """Test community_vectors has title column (VARCHAR 200, nullable)."""
        from core.db.models import CommunityVector

        columns = {c.name: c for c in CommunityVector.__table__.columns}
        assert "title" in columns
        assert columns["title"].nullable is True

    def test_community_vectors_has_summary(self):
        """Test community_vectors has summary column (TEXT, nullable)."""
        from core.db.models import CommunityVector

        columns = {c.name: c for c in CommunityVector.__table__.columns}
        assert "summary" in columns
        assert columns["summary"].nullable is True

    def test_community_vectors_has_entity_count(self):
        """Test community_vectors has entity_count column (INT, NOT NULL, DEFAULT 0)."""
        from core.db.models import CommunityVector

        columns = {c.name: c for c in CommunityVector.__table__.columns}
        assert "entity_count" in columns
        assert columns["entity_count"].nullable is False

    def test_community_vectors_has_article_count(self):
        """Test community_vectors has article_count column (INT, NOT NULL, DEFAULT 0)."""
        from core.db.models import CommunityVector

        columns = {c.name: c for c in CommunityVector.__table__.columns}
        assert "article_count" in columns
        assert columns["article_count"].nullable is False

    def test_community_vectors_has_rank(self):
        """Test community_vectors has rank column (DECIMAL(3,2), nullable)."""
        from core.db.models import CommunityVector

        columns = {c.name: c for c in CommunityVector.__table__.columns}
        assert "rank" in columns
        assert columns["rank"].nullable is True


class TestDailyBriefingMissingColumns:
    """Tests for missing columns on daily_briefings table."""

    def test_daily_briefings_has_title(self):
        """Test daily_briefings has title column (VARCHAR 200, nullable)."""
        from core.db.models import DailyBriefing

        columns = {c.name: c for c in DailyBriefing.__table__.columns}
        assert "title" in columns
        assert columns["title"].nullable is True

    def test_daily_briefings_has_summary(self):
        """Test daily_briefings has summary column (TEXT, nullable)."""
        from core.db.models import DailyBriefing

        columns = {c.name: c for c in DailyBriefing.__table__.columns}
        assert "summary" in columns
        assert columns["summary"].nullable is True

    def test_daily_briefings_has_status(self):
        """Test daily_briefings has status column (VARCHAR 20, NOT NULL, DEFAULT 'draft')."""
        from core.db.models import DailyBriefing

        columns = {c.name: c for c in DailyBriefing.__table__.columns}
        assert "status" in columns
        assert columns["status"].nullable is False

    def test_daily_briefings_briefing_date_is_date_type(self):
        """Test daily_briefings briefing_date is DATE type, not TIMESTAMPTZ."""
        from sqlalchemy import Date as DateType

        from core.db.models import DailyBriefing

        columns = {c.name: c for c in DailyBriefing.__table__.columns}
        assert "briefing_date" in columns
        assert isinstance(columns["briefing_date"].type, DateType)


class TestDailyBriefingItemMissingColumns:
    """Tests for missing columns on daily_briefing_items table."""

    def test_briefing_items_has_score(self):
        """Test daily_briefing_items has score column (DECIMAL(5,3), NOT NULL)."""
        from core.db.models import DailyBriefingItem

        columns = {c.name: c for c in DailyBriefingItem.__table__.columns}
        assert "score" in columns
        assert columns["score"].nullable is False

    def test_briefing_items_has_score_breakdown(self):
        """Test daily_briefing_items has score_breakdown column (JSONB, nullable)."""
        from core.db.models import DailyBriefingItem

        columns = {c.name: c for c in DailyBriefingItem.__table__.columns}
        assert "score_breakdown" in columns
        assert columns["score_breakdown"].nullable is True


class TestSentimentShiftMissingColumns:
    """Tests for missing columns on sentiment_shifts table."""

    def test_sentiment_shifts_has_community_title(self):
        """Test sentiment_shifts has community_title column (VARCHAR 200, nullable)."""
        from core.db.models import SentimentShift

        columns = {c.name: c for c in SentimentShift.__table__.columns}
        assert "community_title" in columns
        assert columns["community_title"].nullable is True

    def test_sentiment_shifts_has_window_start(self):
        """Test sentiment_shifts has window_start column (TIMESTAMPTZ, NOT NULL)."""
        from core.db.models import SentimentShift

        columns = {c.name: c for c in SentimentShift.__table__.columns}
        assert "window_start" in columns
        assert columns["window_start"].nullable is False

    def test_sentiment_shifts_has_window_end(self):
        """Test sentiment_shifts has window_end column (TIMESTAMPTZ, NOT NULL)."""
        from core.db.models import SentimentShift

        columns = {c.name: c for c in SentimentShift.__table__.columns}
        assert "window_end" in columns
        assert columns["window_end"].nullable is False


class TestSourceAuthorityMissingColumns:
    """Tests for missing columns on source_authorities table."""

    def test_source_authorities_has_manual_score(self):
        """Test source_authorities has manual_score column (NUMERIC(3,2), nullable)."""
        from core.db.models import SourceAuthority

        columns = {c.name: c for c in SourceAuthority.__table__.columns}
        assert "manual_score" in columns
        assert columns["manual_score"].nullable is True

    def test_source_authorities_has_final_score(self):
        """Test source_authorities has final_score column (NUMERIC(3,2), nullable)."""
        from core.db.models import SourceAuthority

        columns = {c.name: c for c in SourceAuthority.__table__.columns}
        assert "final_score" in columns
        assert columns["final_score"].nullable is True

    def test_source_authorities_has_article_count(self):
        """Test source_authorities has article_count column (INT, NOT NULL, DEFAULT 0)."""
        from core.db.models import SourceAuthority

        columns = {c.name: c for c in SourceAuthority.__table__.columns}
        assert "article_count" in columns
        assert columns["article_count"].nullable is False

    def test_source_authorities_has_last_crawled_at(self):
        """Test source_authorities has last_crawled_at column (TIMESTAMPTZ, nullable)."""
        from core.db.models import SourceAuthority

        columns = {c.name: c for c in SourceAuthority.__table__.columns}
        assert "last_crawled_at" in columns
        assert columns["last_crawled_at"].nullable is True
