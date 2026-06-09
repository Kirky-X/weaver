# Copyright (c) 2026 KirkyX. All Rights Reserved
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
            "shift_type",
            "direction",
            "magnitude",
            "confidence",
            "detected_at",
            "before_avg",
            "after_avg",
            "trigger_article_ids",
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
        expected = {"id", "briefing_date", "total_items", "generated_at"}
        assert cols == expected

    def test_required_fields(self):
        for field in ("briefing_date", "total_items"):
            assert (
                inspect(DailyBriefing).columns[field].nullable is False
            ), f"{field} should be NOT NULL"

    def test_unique_constraint(self):
        assert inspect(DailyBriefing).columns["briefing_date"].unique is True

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
        expected = {"id", "briefing_id", "article_id", "rank", "category", "reason"}
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
            "created_at",
        }
        assert cols == expected

    def test_required_fields(self):
        for field in ("key_id", "action"):
            assert inspect(AuditLog).columns[field].nullable is False, f"{field} should be NOT NULL"

    def test_optional_fields(self):
        for field in ("target_type", "target_id", "detail", "client_ip"):
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
        expected = {"id", "community_id", "embedding", "model_id", "updated_at"}
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
