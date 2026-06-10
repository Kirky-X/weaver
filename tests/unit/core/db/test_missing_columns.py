# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for database missing columns alignment (Task 6)."""

from __future__ import annotations

import pytest

from core.db.models import (
    CommunityVector,
    DailyBriefing,
    DailyBriefingItem,
    SentimentShift,
    SourceAuthority,
)

# ---------------------------------------------------------------------------
# CommunityVector fields
# ---------------------------------------------------------------------------


class TestCommunityVectorFields:
    """Tests for CommunityVector missing fields per ADD §12.3."""

    def test_has_title_column(self):
        assert "title" in CommunityVector.__table__.columns

    def test_has_summary_column(self):
        assert "summary" in CommunityVector.__table__.columns

    def test_has_entity_count_column(self):
        assert "entity_count" in CommunityVector.__table__.columns

    def test_has_article_count_column(self):
        assert "article_count" in CommunityVector.__table__.columns

    def test_has_rank_column(self):
        assert "rank" in CommunityVector.__table__.columns


# ---------------------------------------------------------------------------
# DailyBriefing fields
# ---------------------------------------------------------------------------


class TestDailyBriefingFields:
    """Tests for DailyBriefing missing fields per ADD §12.2."""

    def test_has_title_column(self):
        assert "title" in DailyBriefing.__table__.columns

    def test_has_summary_column(self):
        assert "summary" in DailyBriefing.__table__.columns

    def test_has_status_column(self):
        assert "status" in DailyBriefing.__table__.columns

    def test_briefing_date_is_date_type(self):
        """briefing_date should be Date type, not DateTime."""
        col = DailyBriefing.__table__.c.briefing_date
        type_name = col.type.__class__.__name__.upper()
        assert "DATE" in type_name


# ---------------------------------------------------------------------------
# DailyBriefingItem fields
# ---------------------------------------------------------------------------


class TestDailyBriefingItemFields:
    """Tests for DailyBriefingItem missing fields per ADD §12.2."""

    def test_has_score_column(self):
        assert "score" in DailyBriefingItem.__table__.columns

    def test_has_score_breakdown_column(self):
        assert "score_breakdown" in DailyBriefingItem.__table__.columns


# ---------------------------------------------------------------------------
# SentimentShift fields
# ---------------------------------------------------------------------------


class TestSentimentShiftFields:
    """Tests for SentimentShift missing fields per ADD §12.1."""

    def test_has_community_title_column(self):
        assert "community_title" in SentimentShift.__table__.columns

    def test_has_window_start_column(self):
        assert "window_start" in SentimentShift.__table__.columns

    def test_has_window_end_column(self):
        assert "window_end" in SentimentShift.__table__.columns


# ---------------------------------------------------------------------------
# SourceAuthority fields
# ---------------------------------------------------------------------------


class TestSourceAuthorityFields:
    """Tests for SourceAuthority missing fields per ADD §12.4."""

    def test_has_manual_score_column(self):
        assert "manual_score" in SourceAuthority.__table__.columns

    def test_has_final_score_column(self):
        assert "final_score" in SourceAuthority.__table__.columns

    def test_has_article_count_column(self):
        assert "article_count" in SourceAuthority.__table__.columns

    def test_has_last_crawled_at_column(self):
        assert "last_crawled_at" in SourceAuthority.__table__.columns
