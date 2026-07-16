# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for CHECK constraints and GIN indexes (Task 7).

Verifies:
- document_type CHECK constraint with correct values
- shift_type CHECK constraint with correct values
- daily_briefing_items.rank CHECK(1-10)
- daily_briefing_items UNIQUE(briefing_id, article_id) and UNIQUE(briefing_id, rank)
- daily_briefings.status CHECK
- doc_metadata GIN index
- community_vectors title GIN index
- emotion_type ENUM includes 兴奋
- interval_minutes CHECK(5-1440)
"""

from __future__ import annotations

import pytest

from core.db.models import (
    ArticleCore,
    CommunityVector,
    DailyBriefing,
    DailyBriefingItem,
    EmotionType,
    SentimentShift,
    SourceConfig as SourceRow,
)


def _get_constraint(model, constraint_type: str, name_contains: str):
    """Get a specific constraint from a model by type and name pattern."""
    for constraint in model.__table__.constraints:
        if (
            constraint.__class__.__name__ == constraint_type
            and name_contains in (constraint.name or "").lower()
        ):
            return constraint
    return None


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
    """document_type SHALL only allow valid values per design doc."""

    def test_document_type_check_exists(self) -> None:
        """ArticleCore SHALL have a CHECK constraint on document_type."""
        check_names = _get_constraint_names(ArticleCore, "CheckConstraint")
        assert any(
            "document_type" in name.lower() for name in check_names
        ), f"No document_type CHECK constraint found in ArticleCore. Existing: {check_names}"

    def test_document_type_values_match_spec(self) -> None:
        """document_type CHECK SHALL include design doc values."""
        constraint = _get_constraint(ArticleCore, "CheckConstraint", "document_type")
        assert constraint is not None
        sql_text = str(constraint.sqltext)
        expected_values = [
            "news",
            "policy",
            "tweet",
            "wechat",
            "blog",
            "report",
            "pdf_doc",
            "social_post",
        ]
        for val in expected_values:
            assert val in sql_text, f"document_type CHECK missing '{val}' in: {sql_text}"


# ---------------------------------------------------------------------------
# 7.2: shift_type CHECK constraint
# ---------------------------------------------------------------------------


class TestShiftTypeCheckConstraint:
    """shift_type SHALL only allow valid values per design doc."""

    def test_shift_type_check_exists(self) -> None:
        """SentimentShift SHALL have a CHECK constraint on shift_type."""
        check_names = _get_constraint_names(SentimentShift, "CheckConstraint")
        assert any(
            "shift_type" in name.lower() for name in check_names
        ), f"No shift_type CHECK constraint found in SentimentShift. Existing: {check_names}"

    def test_shift_type_values_match_spec(self) -> None:
        """shift_type CHECK SHALL include design doc values."""
        constraint = _get_constraint(SentimentShift, "CheckConstraint", "shift_type")
        assert constraint is not None
        sql_text = str(constraint.sqltext)
        expected_values = ["mean_shift", "cumulative_drift", "variance_change"]
        for val in expected_values:
            assert val in sql_text, f"shift_type CHECK missing '{val}' in: {sql_text}"


# ---------------------------------------------------------------------------
# 7.3: rank CHECK(1-10) constraint
# ---------------------------------------------------------------------------


class TestRankCheckConstraint:
    """rank SHALL be between 1 and 10."""

    def test_rank_check_exists(self) -> None:
        """DailyBriefingItem SHALL have a CHECK constraint on rank (1-10)."""
        check_names = _get_constraint_names(DailyBriefingItem, "CheckConstraint")
        assert any(
            "rank" in name.lower() for name in check_names
        ), f"No rank CHECK constraint found in DailyBriefingItem. Existing: {check_names}"

    def test_rank_check_range(self) -> None:
        """rank CHECK SHALL enforce range 1-10."""
        constraint = _get_constraint(DailyBriefingItem, "CheckConstraint", "rank")
        assert constraint is not None
        sql_text = str(constraint.sqltext)
        assert "1" in sql_text and "10" in sql_text, f"rank CHECK not 1-10: {sql_text}"


# ---------------------------------------------------------------------------
# 7.4-7.5: UNIQUE constraints
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
# 7.6: daily_briefings.status CHECK
# ---------------------------------------------------------------------------


class TestBriefingStatusCheckConstraint:
    """Verify existing status CHECK constraint."""

    def test_status_check_exists(self) -> None:
        """DailyBriefing SHALL have a CHECK constraint on status."""
        check_names = _get_constraint_names(DailyBriefing, "CheckConstraint")
        assert "chk_briefing_status" in check_names

    def test_status_values_match_spec(self) -> None:
        """status CHECK SHALL include draft, published, archived."""
        constraint = _get_constraint(DailyBriefing, "CheckConstraint", "briefing_status")
        assert constraint is not None
        sql_text = str(constraint.sqltext)
        for val in ["draft", "published", "archived"]:
            assert val in sql_text, f"status CHECK missing '{val}' in: {sql_text}"


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
        ), f"No doc_metadata GIN index found in ArticleCore. Existing: {index_names}"


# ---------------------------------------------------------------------------
# 7.8: community_vectors title GIN index
# ---------------------------------------------------------------------------


class TestCommunityVectorTitleGinIndex:
    """community_vectors title SHALL have a GIN index for text search."""

    def test_title_gin_index_exists(self) -> None:
        """CommunityVector SHALL have a GIN index on title."""
        index_names = _get_index_names(CommunityVector)
        assert any(
            "title" in name.lower() for name in index_names
        ), f"No title GIN index found in CommunityVector. Existing: {index_names}"


# ---------------------------------------------------------------------------
# 7.9: emotion_type ENUM includes 兴奋
# ---------------------------------------------------------------------------


class TestEmotionTypeEnum:
    """Verify EmotionType enum includes 兴奋."""

    def test_excited_value_exists(self) -> None:
        """EmotionType SHALL include 兴奋 value."""
        assert hasattr(EmotionType, "EXCITED")
        assert EmotionType.EXCITED.value == "兴奋"

    def test_all_ten_values(self) -> None:
        """EmotionType SHALL have all 10 values per design doc."""
        expected_values = [
            "乐观",
            "振奋",
            "兴奋",
            "期待",
            "平静",
            "客观",
            "担忧",
            "悲观",
            "愤怒",
            "恐慌",
        ]
        actual_values = [e.value for e in EmotionType]
        for val in expected_values:
            assert val in actual_values, f"EmotionType missing '{val}'"


# ---------------------------------------------------------------------------
# 7.10: interval_minutes CHECK(5-1440) constraint
# ---------------------------------------------------------------------------


class TestIntervalMinutesCheckConstraint:
    """interval_minutes SHALL be between 5 and 1440."""

    def test_interval_minutes_check_exists(self) -> None:
        """SourceConfig SHALL have a CHECK constraint on interval_minutes (5-1440)."""
        check_names = _get_constraint_names(SourceRow, "CheckConstraint")
        assert any(
            "interval" in name.lower() for name in check_names
        ), f"No interval_minutes CHECK constraint found in SourceConfig. Existing: {check_names}"

    def test_interval_minutes_range(self) -> None:
        """interval_minutes CHECK SHALL enforce range 5-1440."""
        constraint = _get_constraint(SourceRow, "CheckConstraint", "interval")
        assert constraint is not None
        sql_text = str(constraint.sqltext)
        assert (
            "5" in sql_text and "1440" in sql_text
        ), f"interval_minutes CHECK not 5-1440: {sql_text}"
