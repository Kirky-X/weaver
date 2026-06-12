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

    @pytest.mark.parametrize(
        "column", ["title", "summary", "entity_count", "article_count", "rank"]
    )
    def test_has_column(self, column):
        assert column in CommunityVector.__table__.columns


# ---------------------------------------------------------------------------
# DailyBriefing fields
# ---------------------------------------------------------------------------


class TestDailyBriefingFields:
    """Tests for DailyBriefing missing fields per ADD §12.2."""

    @pytest.mark.parametrize("column", ["title", "summary", "status"])
    def test_has_column(self, column):
        assert column in DailyBriefing.__table__.columns

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

    @pytest.mark.parametrize("column", ["score", "score_breakdown"])
    def test_has_column(self, column):
        assert column in DailyBriefingItem.__table__.columns


# ---------------------------------------------------------------------------
# SentimentShift fields
# ---------------------------------------------------------------------------


class TestSentimentShiftFields:
    """Tests for SentimentShift missing fields per ADD §12.1."""

    @pytest.mark.parametrize("column", ["community_title", "window_start", "window_end"])
    def test_has_column(self, column):
        assert column in SentimentShift.__table__.columns


# ---------------------------------------------------------------------------
# SourceAuthority fields
# ---------------------------------------------------------------------------


class TestSourceAuthorityFields:
    """Tests for SourceAuthority missing fields per ADD §12.4."""

    @pytest.mark.parametrize(
        "column", ["manual_score", "final_score", "article_count", "last_crawled_at"]
    )
    def test_has_column(self, column):
        assert column in SourceAuthority.__table__.columns
