# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Foundation classes for SQLAlchemy 2.0 ORM models.

Provides the declarative base, JSON-compatible type decorator, and shared
enum types used across all weaver ORM models.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import JSON, TypeDecorator


# PersistStatus moved to core.protocols.types (protocols must not
# depend on core.db); re-exported here for backwards-compatible imports.
from core.protocols.types import PersistStatus as PersistStatus


class JSONCompatible(TypeDecorator):
    """TypeDecorator that uses JSONB for PostgreSQL and JSON for other dialects.

    DuckDB and SQLite don't support JSONB, only JSON. This decorator
    automatically selects the appropriate type based on the database dialect.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            # Use JSONB for PostgreSQL
            return JSONB().dialect_impl(dialect)
        # Use plain JSON for DuckDB, SQLite, etc.
        return JSON().dialect_impl(dialect)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    type_annotation_map = {
        dict[str, Any]: JSONCompatible,
        list[str]: ARRAY(Text),
        list[uuid.UUID]: ARRAY(UUID(as_uuid=True)),
    }


# ── Enum Types ───────────────────────────────────────────────


class CategoryType(str, enum.Enum):
    POLITICS = "政治"
    MILITARY = "军事"
    ECONOMY = "经济"
    TECHNOLOGY = "科技"
    SOCIETY = "社会"
    CULTURE = "文化"
    SPORTS = "体育"
    INTERNATIONAL = "国际"
    OTHER = "其他"


class EmotionType(str, enum.Enum):
    OPTIMISTIC = "乐观"
    INSPIRED = "振奋"
    EXCITED = "兴奋"
    EXPECTANT = "期待"
    CALM = "平静"
    OBJECTIVE = "客观"
    WORRIED = "担忧"
    PESSIMISTIC = "悲观"
    ANGRY = "愤怒"
    PANIC = "恐慌"


class VectorType(str, enum.Enum):
    TITLE = "title"
    CONTENT = "content"
