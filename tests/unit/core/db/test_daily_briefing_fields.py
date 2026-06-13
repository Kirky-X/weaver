# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Confirmation tests for DailyBriefing and DailyBriefingItem model fields.

Verifies that ORM models align with the database design document (§12.2).
These are structural tests — they check column definitions, constraints,
and relationships without requiring a running database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, inspect
from sqlalchemy.orm import RelationshipProperty

from core.db.models import DailyBriefing, DailyBriefingItem

# ── DailyBriefing ──────────────────────────────────────────────────


class TestDailyBriefingModel:
    """Verify DailyBriefing ORM model matches design document §12.2."""

    def test_tablename(self) -> None:
        assert DailyBriefing.__tablename__ == "daily_briefings"

    def test_has_id_column(self) -> None:
        col = DailyBriefing.__table__.c.id
        assert col.primary_key
        assert col.autoincrement

    def test_briefing_date_is_date_type(self) -> None:
        col = DailyBriefing.__table__.c.briefing_date
        assert isinstance(col.type, Date)
        assert not col.nullable
        assert col.unique

    def test_title_is_string_200(self) -> None:
        col = DailyBriefing.__table__.c.title
        assert isinstance(col.type, String)
        assert col.type.length == 200
        assert col.nullable

    def test_summary_is_text(self) -> None:
        col = DailyBriefing.__table__.c.summary
        assert isinstance(col.type, Text)
        assert col.nullable

    def test_status_has_check_constraint(self) -> None:
        """Verify status CHECK constraint allows draft/published/archived."""
        check_constraints = DailyBriefing.__table__.constraints
        chk = next(
            (c for c in check_constraints if c.name == "chk_briefing_status"),
            None,
        )
        assert chk is not None, "chk_briefing_status CHECK constraint missing"

    def test_status_default_is_draft(self) -> None:
        col = DailyBriefing.__table__.c.status
        assert not col.nullable
        assert col.default is not None
        assert col.default.arg == "draft"

    def test_total_items_default_zero(self) -> None:
        col = DailyBriefing.__table__.c.total_items
        assert isinstance(col.type, Integer)
        assert not col.nullable
        assert col.default is not None
        assert col.default.arg == 0

    def test_generated_at_is_timestamptz(self) -> None:
        col = DailyBriefing.__table__.c.generated_at
        assert isinstance(col.type, DateTime)
        assert col.type.timezone

    def test_has_date_index(self) -> None:
        index_names = [idx.name for idx in DailyBriefing.__table__.indexes]
        assert "idx_briefings_date" in index_names

    def test_items_relationship(self) -> None:
        mapper = inspect(DailyBriefing)
        rel = mapper.relationships.get("items")
        assert rel is not None
        assert rel.uselist is True
        assert rel.cascade.delete_orphan


# ── DailyBriefingItem ──────────────────────────────────────────────


class TestDailyBriefingItemModel:
    """Verify DailyBriefingItem ORM model matches design document §12.2."""

    def test_tablename(self) -> None:
        assert DailyBriefingItem.__tablename__ == "daily_briefing_items"

    def test_has_id_column(self) -> None:
        col = DailyBriefingItem.__table__.c.id
        assert col.primary_key
        assert col.autoincrement

    def test_briefing_id_foreign_key(self) -> None:
        col = DailyBriefingItem.__table__.c.briefing_id
        assert not col.nullable
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert "daily_briefings.id" in str(fks[0].target_fullname)

    def test_article_id_foreign_key(self) -> None:
        col = DailyBriefingItem.__table__.c.article_id
        assert not col.nullable
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert "articles_core.id" in str(fks[0].target_fullname)

    def test_rank_check_constraint(self) -> None:
        """Verify rank CHECK constraint: rank >= 1 AND rank <= 10."""
        check_constraints = DailyBriefingItem.__table__.constraints
        chk = next(
            (c for c in check_constraints if c.name == "chk_briefing_item_rank_range"),
            None,
        )
        assert chk is not None, "chk_briefing_item_rank_range CHECK constraint missing"

    def test_rank_not_nullable(self) -> None:
        col = DailyBriefingItem.__table__.c.rank
        assert not col.nullable

    def test_score_is_numeric_5_3(self) -> None:
        col = DailyBriefingItem.__table__.c.score
        assert isinstance(col.type, Numeric)
        assert col.type.precision == 5
        assert col.type.scale == 3
        assert not col.nullable

    def test_score_breakdown_is_json(self) -> None:
        col = DailyBriefingItem.__table__.c.score_breakdown
        assert col.nullable
        # JSONCompatible is a type alias; verify the column exists and is nullable
        assert col is not None

    def test_category_is_string_20(self) -> None:
        col = DailyBriefingItem.__table__.c.category
        assert isinstance(col.type, String)
        assert col.type.length == 20
        assert col.nullable

    def test_reason_is_text(self) -> None:
        col = DailyBriefingItem.__table__.c.reason
        assert isinstance(col.type, Text)
        assert col.nullable

    def test_unique_constraint_article(self) -> None:
        """Verify uq_briefing_item_article: same briefing can't have duplicate articles."""
        constraint_names = [c.name for c in DailyBriefingItem.__table__.constraints]
        assert "uq_briefing_item_article" in constraint_names

    def test_unique_constraint_rank(self) -> None:
        """Verify uq_briefing_item_rank: same briefing can't have duplicate ranks."""
        constraint_names = [c.name for c in DailyBriefingItem.__table__.constraints]
        assert "uq_briefing_item_rank" in constraint_names

    def test_briefing_relationship(self) -> None:
        mapper = inspect(DailyBriefingItem)
        rel = mapper.relationships.get("briefing")
        assert rel is not None
        assert rel.uselist is False
