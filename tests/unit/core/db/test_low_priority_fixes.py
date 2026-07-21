# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for LOW priority fixes (Task 18).

Verifies:
- 18.1: data_conflicts GIN index on ArticleAnalysis and Article
- 18.2: document_type + publish_time composite index on ArticleCore and Article
- 18.3: AuditLog.client_ip column type is String(45) with documentation
- 18.4: DailyBriefingItem UNIQUE(briefing_id, article_id) and UNIQUE(briefing_id, rank)
"""

from __future__ import annotations

from sqlalchemy import String

from core.db.models import Article, ArticleAnalysis, ArticleCore, AuditLog, DailyBriefingItem


def _get_index_names(model) -> set[str]:
    """Get names of indexes from a model."""
    return {idx.name for idx in model.__table__.indexes}


def _get_index(model, name: str):
    """Get a specific index by name from a model."""
    for idx in model.__table__.indexes:
        if idx.name == name:
            return idx
    return None


def _get_constraint_names(model, constraint_type: str) -> set[str]:
    """Get names of constraints of a given type from a model."""
    names: set[str] = set()
    for constraint in model.__table__.constraints:
        if constraint.__class__.__name__ == constraint_type:
            names.add(constraint.name)
    return names


# ---------------------------------------------------------------------------
# 18.1: data_conflicts GIN index
# ---------------------------------------------------------------------------


class TestDataConflictsGinIndex:
    """data_conflicts SHALL have a GIN index for JSONB queries."""

    def test_article_analysis_data_conflicts_gin_index_exists(self) -> None:
        """ArticleAnalysis SHALL have a GIN index on data_conflicts."""
        index_names = _get_index_names(ArticleAnalysis)
        assert "idx_core_data_conflicts_gin" in index_names, (
            f"No data_conflicts GIN index found in ArticleAnalysis. Existing: {index_names}"
        )

    def test_article_analysis_data_conflicts_gin_index_uses_gin(self) -> None:
        """ArticleAnalysis data_conflicts GIN index SHALL use postgresql_using='gin'."""
        idx = _get_index(ArticleAnalysis, "idx_core_data_conflicts_gin")
        assert idx is not None
        assert idx.dialect_options.get("postgresql", {}).get("using") == "gin", (
            f"data_conflicts GIN index not using GIN: {idx.dialect_options}"
        )

    def test_article_data_conflicts_gin_index_exists(self) -> None:
        """Article SHALL have a GIN index on data_conflicts."""
        index_names = _get_index_names(Article)
        assert "idx_articles_data_conflicts_gin" in index_names, (
            f"No data_conflicts GIN index found in Article. Existing: {index_names}"
        )

    def test_article_data_conflicts_gin_index_uses_gin(self) -> None:
        """Article data_conflicts GIN index SHALL use postgresql_using='gin'."""
        idx = _get_index(Article, "idx_articles_data_conflicts_gin")
        assert idx is not None
        assert idx.dialect_options.get("postgresql", {}).get("using") == "gin", (
            f"data_conflicts GIN index not using GIN: {idx.dialect_options}"
        )


# ---------------------------------------------------------------------------
# 18.2: document_type + publish_time composite index
# ---------------------------------------------------------------------------


class TestDocumentTypePublishTimeIndex:
    """document_type + publish_time SHALL have a composite index."""

    def test_article_core_composite_index_exists(self) -> None:
        """ArticleCore SHALL have a composite index on document_type + publish_time."""
        index_names = _get_index_names(ArticleCore)
        assert "idx_core_document_type_publish" in index_names, (
            f"No document_type+publish_time composite index found in ArticleCore. "
            f"Existing: {index_names}"
        )

    def test_article_core_composite_index_columns(self) -> None:
        """ArticleCore composite index SHALL cover document_type and publish_time."""
        idx = _get_index(ArticleCore, "idx_core_document_type_publish")
        assert idx is not None
        col_names = [col.name for col in idx.columns]
        assert "document_type" in col_names, f"document_type not in index columns: {col_names}"

    def test_article_composite_index_exists(self) -> None:
        """Article SHALL have a composite index on document_type + publish_time."""
        index_names = _get_index_names(Article)
        assert "idx_articles_document_type_publish" in index_names, (
            f"No document_type+publish_time composite index found in Article. "
            f"Existing: {index_names}"
        )

    def test_article_composite_index_columns(self) -> None:
        """Article composite index SHALL cover document_type and publish_time."""
        idx = _get_index(Article, "idx_articles_document_type_publish")
        assert idx is not None
        col_names = [col.name for col in idx.columns]
        assert "document_type" in col_names, f"document_type not in index columns: {col_names}"


# ---------------------------------------------------------------------------
# 18.3: AuditLog.client_ip — String(45) with documentation
# ---------------------------------------------------------------------------


class TestAuditLogClientIp:
    """client_ip SHALL be String(45) for DuckDB compatibility."""

    def test_client_ip_column_type_is_string(self) -> None:
        """AuditLog.client_ip SHALL be String type."""
        col = AuditLog.__table__.columns["client_ip"]
        assert isinstance(col.type, String), (
            f"client_ip column type is {type(col.type).__name__}, expected String"
        )

    def test_client_ip_column_length_is_45(self) -> None:
        """AuditLog.client_ip SHALL be String(45) for IPv6 support."""
        col = AuditLog.__table__.columns["client_ip"]
        assert col.type.length == 45, f"client_ip column length is {col.type.length}, expected 45"


# ---------------------------------------------------------------------------
# 18.4: DailyBriefingItem UNIQUE constraints
# ---------------------------------------------------------------------------


class TestBriefingItemUniqueConstraints:
    """DailyBriefingItem SHALL have UNIQUE(briefing_id, article_id) and UNIQUE(briefing_id, rank)."""

    def test_briefing_item_article_unique_exists(self) -> None:
        """DailyBriefingItem SHALL have UNIQUE(briefing_id, article_id)."""
        unique_names = _get_constraint_names(DailyBriefingItem, "UniqueConstraint")
        assert "uq_briefing_item_article" in unique_names

    def test_briefing_item_rank_unique_exists(self) -> None:
        """DailyBriefingItem SHALL have UNIQUE(briefing_id, rank)."""
        unique_names = _get_constraint_names(DailyBriefingItem, "UniqueConstraint")
        assert "uq_briefing_item_rank" in unique_names
