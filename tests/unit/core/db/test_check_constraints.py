# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for CHECK constraints and GIN indexes (Task 7)."""

from __future__ import annotations

import pytest

from core.db.models import (
    ArticleCore,
    CommunityVector,
    DailyBriefing,
    DailyBriefingItem,
    SentimentShift,
    Source,
)


def _get_constraint_names(model, constraint_type: str) -> set[str]:
    """Get names of constraints of a given type from a model."""
    names: set[str] = set()
    for constraint in model.__table__.constraints:
        if constraint.__class__.__name__ == constraint_type:
            names.add(constraint.name)
    return names


def _get_index_names(model) -> set[str]:
    """Get names of indexes from a model."""
    return {idx.name for idx in model.__table__.indexes}


# ---------------------------------------------------------------------------
# 7.1: document_type CHECK constraint
# ---------------------------------------------------------------------------


class TestDocumentTypeCheckConstraint:
    """document_type SHALL only allow valid values."""

    def test_document_type_check_exists(self) -> None:
        """ArticleCore SHALL have a CHECK constraint on document_type."""
        check_names = _get_constraint_names(ArticleCore, "CheckConstraint")
        assert any("document_type" in name.lower() for name in check_names), (
            f"No document_type CHECK constraint found in ArticleCore. " f"Existing: {check_names}"
        )


# ---------------------------------------------------------------------------
# 7.2: shift_type CHECK constraint
# ---------------------------------------------------------------------------


class TestShiftTypeCheckConstraint:
    """shift_type SHALL only allow valid values."""

    def test_shift_type_check_exists(self) -> None:
        """SentimentShift SHALL have a CHECK constraint on shift_type."""
        check_names = _get_constraint_names(SentimentShift, "CheckConstraint")
        assert any("shift_type" in name.lower() for name in check_names), (
            f"No shift_type CHECK constraint found in SentimentShift. " f"Existing: {check_names}"
        )


# ---------------------------------------------------------------------------
# 7.3: rank CHECK(1-10) constraint
# ---------------------------------------------------------------------------


class TestRankCheckConstraint:
    """rank SHALL be between 1 and 10."""

    def test_rank_check_exists(self) -> None:
        """DailyBriefingItem SHALL have a CHECK constraint on rank (1-10)."""
        check_names = _get_constraint_names(DailyBriefingItem, "CheckConstraint")
        assert any("rank" in name.lower() for name in check_names), (
            f"No rank CHECK constraint found in DailyBriefingItem. " f"Existing: {check_names}"
        )


# ---------------------------------------------------------------------------
# 7.4-7.5: Already exist (verified in models.py)
# ---------------------------------------------------------------------------


class TestExistingUniqueConstraints:
    """Verify existing UNIQUE constraints that were already present."""

    def test_briefing_item_article_unique_exists(self) -> None:
        """DailyBriefingItem SHALL have UNIQUE(briefing_id, article_id)."""
        unique_names = _get_constraint_names(DailyBriefingItem, "UniqueConstraint")
        assert "uq_briefing_item_article" in unique_names

    def test_briefing_item_rank_unique_exists(self) -> None:
        """DailyBriefingItem SHALL have UNIQUE(briefing_id, rank)."""
        unique_names = _get_constraint_names(DailyBriefingItem, "UniqueConstraint")
        assert "uq_briefing_item_rank" in unique_names


# ---------------------------------------------------------------------------
# 7.6: Already exists (verified in models.py)
# ---------------------------------------------------------------------------


class TestBriefingStatusCheckConstraint:
    """Verify existing status CHECK constraint."""

    def test_status_check_exists(self) -> None:
        """DailyBriefing SHALL have a CHECK constraint on status."""
        check_names = _get_constraint_names(DailyBriefing, "CheckConstraint")
        assert "chk_briefing_status" in check_names


# ---------------------------------------------------------------------------
# 7.7: doc_metadata GIN index
# ---------------------------------------------------------------------------


class TestDocMetadataGinIndex:
    """doc_metadata SHALL have a GIN index for JSONB queries."""

    def test_doc_metadata_gin_index_exists(self) -> None:
        """ArticleCore SHALL have a GIN index on doc_metadata."""
        index_names = _get_index_names(ArticleCore)
        assert any(
            "doc_metadata" in name.lower() or "metadata" in name.lower() for name in index_names
        ), (f"No doc_metadata GIN index found in ArticleCore. " f"Existing: {index_names}")


# ---------------------------------------------------------------------------
# 7.8: community_vectors title GIN index
# ---------------------------------------------------------------------------


class TestCommunityVectorTitleGinIndex:
    """community_vectors title SHALL have a GIN index for text search."""

    def test_title_gin_index_exists(self) -> None:
        """CommunityVector SHALL have a GIN index on title."""
        index_names = _get_index_names(CommunityVector)
        assert any("title" in name.lower() for name in index_names), (
            f"No title GIN index found in CommunityVector. " f"Existing: {index_names}"
        )


# ---------------------------------------------------------------------------
# 7.9: emotion_type ENUM includes 兴奋 (already exists, verify)
# ---------------------------------------------------------------------------


class TestEmotionTypeEnum:
    """Verify EmotionType enum includes 兴奋."""

    def test_excited_value_exists(self) -> None:
        """EmotionType SHALL include 兴奋 value."""
        from core.db.models import EmotionType

        assert hasattr(EmotionType, "EXCITED")
        assert EmotionType.EXCITED.value == "兴奋"


# ---------------------------------------------------------------------------
# 7.10: interval_minutes CHECK(5-1440) constraint
# ---------------------------------------------------------------------------


class TestIntervalMinutesCheckConstraint:
    """interval_minutes SHALL be between 5 and 1440."""

    def test_interval_minutes_check_exists(self) -> None:
        """Source SHALL have a CHECK constraint on interval_minutes (5-1440)."""
        check_names = _get_constraint_names(Source, "CheckConstraint")
        assert any("interval" in name.lower() for name in check_names), (
            f"No interval_minutes CHECK constraint found in Source. " f"Existing: {check_names}"
        )
