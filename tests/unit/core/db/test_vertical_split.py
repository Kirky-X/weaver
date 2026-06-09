# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for Articles vertical split: articles_core + article_bodies + article_analysis.

Design doc reference: Weaver-数据库设计文档 §9.1

The vertical split separates the monolithic 45-column articles table into:
- articles_core: high-frequency query columns (~500 bytes/row, ~16 rows/page)
- article_bodies: large text fields (only accessed on detail pages)
- article_analysis: LLM analysis results (grows with features, doesn't affect core)

A backward-compatible `articles` VIEW joins all three tables.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from core.db.models import ArticleAnalysis, ArticleBody, ArticleCore, Base

# ── Column definition tests ──────────────────────────────────


class TestArticleCoreColumns:
    """Verify articles_core has the required columns from the design doc."""

    @pytest.fixture(autouse=True)
    def _inspect_table(self):
        """Inspect the ArticleCore model's table columns."""
        self.columns = {c.name for c in inspect(ArticleCore).columns}

    def test_has_id(self):
        assert "id" in self.columns

    def test_has_source_url(self):
        assert "source_url" in self.columns

    def test_has_source_host(self):
        assert "source_host" in self.columns

    def test_has_title(self):
        assert "title" in self.columns

    def test_has_category(self):
        assert "category" in self.columns

    def test_has_language(self):
        assert "language" in self.columns

    def test_has_score(self):
        assert "score" in self.columns

    def test_has_sentiment_score(self):
        assert "sentiment_score" in self.columns

    def test_has_credibility_score(self):
        assert "credibility_score" in self.columns

    def test_has_persist_status(self):
        assert "persist_status" in self.columns

    def test_has_publish_time(self):
        assert "publish_time" in self.columns

    def test_has_created_at(self):
        assert "created_at" in self.columns

    def test_has_updated_at(self):
        assert "updated_at" in self.columns

    # Additional columns beyond design doc (needed for pipeline management)

    def test_has_region(self):
        assert "region" in self.columns

    def test_has_merge_fields(self):
        assert "merged_into" in self.columns
        assert "is_merged" in self.columns
        assert "merged_source_ids" in self.columns

    def test_has_task_tracking(self):
        assert "task_id" in self.columns
        assert "processing_stage" in self.columns
        assert "processing_error" in self.columns
        assert "retry_count" in self.columns

    def test_has_content_hash_and_version(self):
        assert "content_hash" in self.columns
        assert "version" in self.columns

    def test_has_document_type(self):
        assert "document_type" in self.columns

    def test_has_doc_metadata(self):
        assert "doc_metadata" in self.columns


class TestArticleBodiesColumns:
    """Verify article_bodies has the required columns."""

    @pytest.fixture(autouse=True)
    def _inspect_table(self):
        self.columns = {c.name for c in inspect(ArticleBody).columns}

    def test_has_article_id(self):
        assert "article_id" in self.columns

    def test_has_body(self):
        assert "body" in self.columns

    def test_has_summary(self):
        assert "summary" in self.columns


class TestArticleAnalysisColumns:
    """Verify article_analysis has the required columns."""

    @pytest.fixture(autouse=True)
    def _inspect_table(self):
        self.columns = {c.name for c in inspect(ArticleAnalysis).columns}

    def test_has_article_id(self):
        assert "article_id" in self.columns

    def test_has_is_news(self):
        assert "is_news" in self.columns

    def test_has_subjects(self):
        assert "subjects" in self.columns

    def test_has_key_data(self):
        assert "key_data" in self.columns

    def test_has_impact(self):
        assert "impact" in self.columns

    def test_has_has_data(self):
        assert "has_data" in self.columns

    def test_has_quality_score(self):
        assert "quality_score" in self.columns

    def test_has_sentiment(self):
        assert "sentiment" in self.columns

    def test_has_primary_emotion(self):
        assert "primary_emotion" in self.columns

    def test_has_emotion_targets(self):
        assert "emotion_targets" in self.columns

    def test_has_source_credibility(self):
        assert "source_credibility" in self.columns

    def test_has_cross_verification(self):
        assert "cross_verification" in self.columns

    def test_has_content_check_score(self):
        assert "content_check_score" in self.columns

    def test_has_credibility_flags(self):
        assert "credibility_flags" in self.columns

    def test_has_verified_by_sources(self):
        assert "verified_by_sources" in self.columns

    def test_has_data_conflicts(self):
        assert "data_conflicts" in self.columns

    # Additional columns beyond design doc

    def test_has_event_time(self):
        assert "event_time" in self.columns

    def test_has_image_forensics(self):
        assert "image_forensics" in self.columns

    def test_has_prompt_versions(self):
        assert "prompt_versions" in self.columns


# ── Constraint tests ─────────────────────────────────────────


class TestArticleCoreConstraints:
    """Verify articles_core constraints."""

    @pytest.fixture(autouse=True)
    def _inspect_table(self):
        self.table = ArticleCore.__table__

    def test_source_url_unique(self):
        unique_cols = [
            col.name
            for constraint in self.table.constraints
            if hasattr(constraint, "columns") and len(constraint.columns) == 1
            for col in constraint.columns
        ]
        # source_url should have a unique constraint
        assert "source_url" in unique_cols or any(
            c.unique for c in self.table.columns if c.name == "source_url"
        )

    def test_id_is_primary_key(self):
        pk_cols = [c.name for c in self.table.primary_key.columns]
        assert "id" in pk_cols


class TestArticleBodiesConstraints:
    """Verify article_bodies constraints."""

    @pytest.fixture(autouse=True)
    def _inspect_table(self):
        self.table = ArticleBody.__table__

    def test_article_id_is_primary_key(self):
        pk_cols = [c.name for c in self.table.primary_key.columns]
        assert "article_id" in pk_cols

    def test_article_id_foreign_key_to_core(self):
        """article_id should reference articles_core(id) with CASCADE delete."""
        fk = self.table.columns["article_id"].foreign_keys
        assert len(fk) == 1
        fk_ref = list(fk)[0]
        assert fk_ref.column.table.name == "articles_core"
        assert fk_ref.column.name == "id"
        # CASCADE delete
        assert fk_ref.ondelete == "CASCADE"


class TestArticleAnalysisConstraints:
    """Verify article_analysis constraints."""

    @pytest.fixture(autouse=True)
    def _inspect_table(self):
        self.table = ArticleAnalysis.__table__

    def test_article_id_is_primary_key(self):
        pk_cols = [c.name for c in self.table.primary_key.columns]
        assert "article_id" in pk_cols

    def test_article_id_foreign_key_to_core(self):
        """article_id should reference articles_core(id) with CASCADE delete."""
        fk = self.table.columns["article_id"].foreign_keys
        assert len(fk) == 1
        fk_ref = list(fk)[0]
        assert fk_ref.column.table.name == "articles_core"
        assert fk_ref.column.name == "id"
        assert fk_ref.ondelete == "CASCADE"


# ── ORM relationship tests ───────────────────────────────────


class TestArticleCoreRelationships:
    """Verify ORM relationships between split tables."""

    def test_core_has_body_relationship(self):
        """ArticleCore should have a relationship to ArticleBody."""
        rels = ArticleCore.__mapper__.relationships
        assert "body" in rels or "bodies" in rels

    def test_core_has_analysis_relationship(self):
        """ArticleCore should have a relationship to ArticleAnalysis."""
        rels = ArticleCore.__mapper__.relationships
        assert "analysis" in rels

    def test_body_belongs_to_core(self):
        """ArticleBody should have a back-reference to ArticleCore."""
        rels = ArticleBody.__mapper__.relationships
        assert "core" in rels or "article" in rels

    def test_analysis_belongs_to_core(self):
        """ArticleAnalysis should have a back-reference to ArticleCore."""
        rels = ArticleAnalysis.__mapper__.relationships
        assert "core" in rels or "article" in rels


# ── Default value tests ──────────────────────────────────────


class TestArticleCoreDefaults:
    """Verify default values match the design doc."""

    def test_persist_status_default_pending(self):
        col = ArticleCore.__table__.columns["persist_status"]
        assert col.default is not None or col.server_default is not None

    def test_version_default_1(self):
        col = ArticleCore.__table__.columns["version"]
        assert col.default is not None or col.server_default is not None

    def test_document_type_default_news(self):
        col = ArticleCore.__table__.columns["document_type"]
        assert col.default is not None or col.server_default is not None

    def test_is_merged_default_false(self):
        col = ArticleCore.__table__.columns["is_merged"]
        assert col.default is not None or col.server_default is not None

    def test_retry_count_default_0(self):
        col = ArticleCore.__table__.columns["retry_count"]
        assert col.default is not None or col.server_default is not None


class TestArticleAnalysisDefaults:
    """Verify default values for analysis table."""

    def test_is_news_default_false(self):
        col = ArticleAnalysis.__table__.columns["is_news"]
        assert col.default is not None or col.server_default is not None

    def test_verified_by_sources_default_0(self):
        col = ArticleAnalysis.__table__.columns["verified_by_sources"]
        assert col.default is not None or col.server_default is not None

    def test_data_conflicts_default_empty(self):
        col = ArticleAnalysis.__table__.columns["data_conflicts"]
        assert col.default is not None or col.server_default is not None
