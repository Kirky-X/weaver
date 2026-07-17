# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for ORM model definitions (sentiment_shifts, daily_briefings, etc.)."""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import inspect

from core.db.models import (
    AuditLog,
    Base,
    CommunityVector,
    DailyBriefing,
    DailyBriefingItem,
    SentimentShift,
)


def _get_column_names(model: type[Base]) -> set[str]:
    """Get column names from an ORM model using SQLAlchemy inspection."""
    mapper = inspect(model)
    return {c.key for c in mapper.columns}


def _get_column_type(model: type[Base], column: str) -> Any:
    """Get column type from an ORM model."""
    mapper = inspect(model)
    col = next(c for c in mapper.columns if c.key == column)
    return type(col.type)


class TestSentimentShiftModel:
    """Test SentimentShift ORM model definition."""

    def test_model_exists(self):
        assert SentimentShift.__tablename__ == "sentiment_shifts"

    def test_columns(self):
        cols = _get_column_names(SentimentShift)
        expected = {
            "id",
            "community_id",
            "community_title",
            "shift_type",
            "direction",
            "magnitude",
            "confidence",
            "detected_at",
            "window_start",
            "window_end",
            "before_avg",
            "after_avg",
            "trigger_article_ids",
            # Migration 30: article-level tracking fields (T003 SentimentTrackerNode)
            "article_id",
            "entity_name",
            "shift_value",
            "created_at",
        }
        assert cols == expected

    def test_required_fields(self):
        for field in (
            "community_id",
            "shift_type",
            "direction",
            "magnitude",
            "confidence",
            "detected_at",
        ):
            assert (
                inspect(SentimentShift).columns[field].nullable is False
            ), f"{field} should be NOT NULL"

    def test_optional_fields(self):
        for field in ("before_avg", "after_avg", "trigger_article_ids"):
            assert (
                inspect(SentimentShift).columns[field].nullable is True
            ), f"{field} should be nullable"

    def test_indexes(self):
        indexes = {idx.name for idx in SentimentShift.__table_args__ if hasattr(idx, "name")}
        assert "idx_shifts_community" in indexes
        assert "idx_shifts_type" in indexes
        assert "idx_shifts_detected" in indexes


class TestDailyBriefingModel:
    """Test DailyBriefing ORM model definition."""

    def test_model_exists(self):
        assert DailyBriefing.__tablename__ == "daily_briefings"

    def test_columns(self):
        cols = _get_column_names(DailyBriefing)
        expected = {
            "id",
            "briefing_date",
            "title",
            "summary",
            "status",
            "total_items",
            "generated_at",
            # Migration 32 (T004): added category column for per-category
            # briefings (finance/tech/ai/general).
            "category",
        }
        assert cols == expected

    def test_required_fields(self):
        for field in ("briefing_date", "total_items"):
            assert (
                inspect(DailyBriefing).columns[field].nullable is False
            ), f"{field} should be NOT NULL"

    def test_unique_constraint(self):
        # Migration 32: single-column unique on briefing_date dropped in
        # favor of composite UNIQUE(briefing_date, category). Verify the
        # composite constraint exists and column-level unique is None.
        assert inspect(DailyBriefing).columns["briefing_date"].unique is None
        constraint_names = [c.name for c in DailyBriefing.__table__.constraints]
        assert "uq_briefings_date_category" in constraint_names

    def test_indexes(self):
        indexes = {idx.name for idx in DailyBriefing.__table_args__ if hasattr(idx, "name")}
        assert "idx_briefings_date" in indexes

    def test_relationship_items(self):
        assert hasattr(DailyBriefing, "items")


class TestDailyBriefingItemModel:
    """Test DailyBriefingItem ORM model definition."""

    def test_model_exists(self):
        assert DailyBriefingItem.__tablename__ == "daily_briefing_items"

    def test_columns(self):
        cols = _get_column_names(DailyBriefingItem)
        expected = {
            "id",
            "briefing_id",
            "article_id",
            "rank",
            "score",
            "score_breakdown",
            "category",
            "reason",
        }
        assert cols == expected

    def test_foreign_keys(self):
        mapper = inspect(DailyBriefingItem)
        fk_column_names = set()
        for col in mapper.columns:
            for fk in col.foreign_keys:
                fk_column_names.add(fk.parent.name)
        assert "briefing_id" in fk_column_names
        assert "article_id" in fk_column_names

    def test_relationship_briefing(self):
        assert hasattr(DailyBriefingItem, "briefing")


class TestAuditLogModel:
    """Test AuditLog ORM model definition."""

    def test_model_exists(self):
        assert AuditLog.__tablename__ == "audit_log"

    def test_columns(self):
        cols = _get_column_names(AuditLog)
        expected = {
            "id",
            "key_id",
            "action",
            "target_type",
            "target_id",
            "detail",
            "client_ip",
            "user_agent",
            "created_at",
        }
        assert cols == expected

    def test_required_fields(self):
        for field in ("key_id", "action"):
            assert inspect(AuditLog).columns[field].nullable is False, f"{field} should be NOT NULL"

    def test_optional_fields(self):
        for field in ("target_type", "target_id", "detail", "client_ip", "user_agent"):
            assert inspect(AuditLog).columns[field].nullable is True, f"{field} should be nullable"

    def test_indexes(self):
        indexes = {idx.name for idx in AuditLog.__table_args__ if hasattr(idx, "name")}
        assert "idx_audit_occurred" in indexes
        assert "idx_audit_key" in indexes


class TestCommunityVectorModel:
    """Test CommunityVector ORM model definition."""

    def test_model_exists(self):
        assert CommunityVector.__tablename__ == "community_vectors"

    def test_columns(self):
        cols = _get_column_names(CommunityVector)
        expected = {
            "id",
            "community_id",
            "embedding",
            "model_id",
            "title",
            "summary",
            "entity_count",
            "article_count",
            "rank",
            "updated_at",
        }
        assert cols == expected

    def test_required_fields(self):
        for field in ("community_id", "embedding", "model_id"):
            assert (
                inspect(CommunityVector).columns[field].nullable is False
            ), f"{field} should be NOT NULL"

    def test_unique_community_id(self):
        assert inspect(CommunityVector).columns["community_id"].unique is True

    def test_hnsw_index(self):
        hnsw = [
            idx
            for idx in CommunityVector.__table_args__
            if hasattr(idx, "kwargs") and idx.kwargs.get("postgresql_using") == "hnsw"
        ]
        assert len(hnsw) == 1, "Expected exactly one HNSW index"
        assert hnsw[0].kwargs.get("postgresql_with") == {"m": 16, "ef_construction": 200}
