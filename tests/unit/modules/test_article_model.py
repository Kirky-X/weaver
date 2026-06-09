# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Article model task_id field."""

from __future__ import annotations

import uuid
from typing import Any

from core.db import Article, PersistStatus


class TestArticleTaskIdField:
    """Tests for Article.task_id field."""

    def test_article_has_task_id_attribute(self):
        """Test that Article model has task_id attribute."""
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Test content",
            persist_status=PersistStatus.PENDING,
        )
        assert hasattr(article, "task_id")

    def test_article_task_id_defaults_to_none(self):
        """Test backward compatibility - task_id defaults to None."""
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Test content",
            persist_status=PersistStatus.PENDING,
        )
        assert article.task_id is None

    def test_article_can_be_created_with_task_id(self):
        """Test creating an article with a specific task_id."""
        task_id = uuid.uuid4()
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Test content",
            persist_status=PersistStatus.PENDING,
            task_id=task_id,
        )
        assert article.task_id == task_id
        assert article.task_id is not None

    def test_article_task_id_is_uuid_type(self):
        """Test that task_id is a valid UUID type."""
        task_id = uuid.uuid4()
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Test content",
            persist_status=PersistStatus.PENDING,
            task_id=task_id,
        )
        assert isinstance(article.task_id, uuid.UUID)

    def test_article_task_id_can_be_updated(self):
        """Test that task_id can be updated after creation."""
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Test content",
            persist_status=PersistStatus.PENDING,
        )
        task_id = uuid.uuid4()
        article.task_id = task_id
        assert article.task_id == task_id


class TestArticlePersistStatusTransitions:
    """Tests for persist_status transitions with task_id articles."""

    def test_valid_transition_pending_to_processing(self):
        """Test valid transition: PENDING -> PROCESSING."""
        assert PersistStatus.is_valid_transition(PersistStatus.PENDING, PersistStatus.PROCESSING)

    def test_valid_transition_processing_to_pg_done(self):
        """Test valid transition: PROCESSING -> PG_DONE."""
        assert PersistStatus.is_valid_transition(PersistStatus.PROCESSING, PersistStatus.PG_DONE)

    def test_invalid_transition_processing_to_neo4j_done(self):
        assert not PersistStatus.is_valid_transition(
            PersistStatus.PROCESSING, PersistStatus.NEO4J_DONE
        )

    def test_valid_transition_neo4j_done_to_neo4j_done(self):
        assert PersistStatus.is_valid_transition(PersistStatus.NEO4J_DONE, PersistStatus.NEO4J_DONE)

    def test_valid_transition_pg_done_to_neo4j_done(self):
        assert PersistStatus.is_valid_transition(PersistStatus.PG_DONE, PersistStatus.NEO4J_DONE)

    def test_valid_transition_pg_done_to_failed(self):
        assert PersistStatus.is_valid_transition(PersistStatus.PG_DONE, PersistStatus.FAILED)

    def test_invalid_transition_pg_done_to_pending(self):
        assert not PersistStatus.is_valid_transition(PersistStatus.PG_DONE, PersistStatus.PENDING)

    def test_invalid_transition_neo4j_done_to_pending(self):
        assert not PersistStatus.is_valid_transition(
            PersistStatus.NEO4J_DONE, PersistStatus.PENDING
        )

    def test_invalid_transition_neo4j_done_to_processing(self):
        assert not PersistStatus.is_valid_transition(
            PersistStatus.NEO4J_DONE, PersistStatus.PROCESSING
        )

    def test_valid_transition_pg_done_to_pg_done(self):
        assert PersistStatus.is_valid_transition(PersistStatus.PG_DONE, PersistStatus.PG_DONE)


class TestArticleNewFields:
    """Tests for Article model new content enrichment fields."""

    def test_data_conflicts_column_exists(self):
        assert hasattr(Article, "data_conflicts")
        col = Article.__table__.c["data_conflicts"]
        assert col is not None

    def test_data_conflicts_column_defaults(self):
        col = Article.__table__.c["data_conflicts"]
        assert col.default is not None
        assert col.default.is_callable
        assert col.server_default is not None
        assert not col.nullable

    def test_data_conflicts_custom_value(self):
        conflicts: list[dict[str, Any]] = [
            {"field": "title", "source_a": "value1", "source_b": "value2"}
        ]
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Test content",
            persist_status=PersistStatus.PENDING,
            data_conflicts=conflicts,
        )
        assert article.data_conflicts == conflicts
        assert len(article.data_conflicts) == 1

    def test_image_forensics_column_exists(self):
        assert hasattr(Article, "image_forensics")
        col = Article.__table__.c["image_forensics"]
        assert col is not None

    def test_image_forensics_column_defaults(self):
        col = Article.__table__.c["image_forensics"]
        assert col.default is not None
        assert col.default.is_callable
        assert col.server_default is not None
        assert not col.nullable

    def test_image_forensics_custom_value(self):
        forensics: list[dict[str, Any]] = [
            {"image_url": "https://example.com/photo.jpg", "is_ai_generated": True}
        ]
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Test content",
            persist_status=PersistStatus.PENDING,
            image_forensics=forensics,
        )
        assert article.image_forensics == forensics

    def test_document_type_column_exists(self):
        assert hasattr(Article, "document_type")
        col = Article.__table__.c["document_type"]
        assert col is not None

    def test_document_type_column_defaults(self):
        col = Article.__table__.c["document_type"]
        assert col.default is not None
        assert col.default.arg == "news"
        assert col.server_default is not None
        assert not col.nullable

    def test_document_type_custom_value(self):
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Test content",
            persist_status=PersistStatus.PENDING,
            document_type="press_release",
        )
        assert article.document_type == "press_release"

    def test_doc_metadata_column_exists(self):
        assert hasattr(Article, "doc_metadata")
        col = Article.__table__.c["doc_metadata"]
        assert col is not None

    def test_doc_metadata_column_defaults(self):
        col = Article.__table__.c["doc_metadata"]
        assert col.default is not None
        assert col.default.is_callable
        assert col.server_default is not None
        assert not col.nullable

    def test_doc_metadata_custom_value(self):
        metadata = {"source_agency": "Reuters", "byline": "John Doe"}
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Test content",
            persist_status=PersistStatus.PENDING,
            doc_metadata=metadata,
        )
        assert article.doc_metadata == metadata

    def test_content_hash_column_exists(self):
        assert hasattr(Article, "content_hash")
        col = Article.__table__.c["content_hash"]
        assert col is not None

    def test_content_hash_nullable(self):
        col = Article.__table__.c["content_hash"]
        assert col.nullable
        assert col.default is None

    def test_content_hash_custom_value(self):
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Test content",
            persist_status=PersistStatus.PENDING,
            content_hash="abc123def456",
        )
        assert article.content_hash == "abc123def456"

    def test_content_hash_max_length(self):
        hash_value = "a" * 64
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Test content",
            persist_status=PersistStatus.PENDING,
            content_hash=hash_value,
        )
        assert article.content_hash == hash_value
        assert len(article.content_hash) == 64

    def test_version_column_exists(self):
        assert hasattr(Article, "version")
        col = Article.__table__.c["version"]
        assert col is not None

    def test_version_column_defaults(self):
        col = Article.__table__.c["version"]
        assert col.default is not None
        assert col.default.arg == 1
        assert col.server_default is not None
        assert not col.nullable

    def test_version_custom_value(self):
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Test content",
            persist_status=PersistStatus.PENDING,
            version=3,
        )
        assert article.version == 3

    def test_version_increment(self):
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Test content",
            persist_status=PersistStatus.PENDING,
            version=2,
        )
        article.version += 1
        assert article.version == 3

    def test_all_new_fields_in_article_instance(self):
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Test content",
            persist_status=PersistStatus.PENDING,
            data_conflicts=[{"field": "title", "diff": "changed"}],
            image_forensics=[{"image_url": "https://example.com/img.jpg"}],
            document_type="analysis",
            doc_metadata={"author": "AI"},
            content_hash="sha256hashvalue",
            version=2,
        )
        assert article.data_conflicts == [{"field": "title", "diff": "changed"}]
        assert article.image_forensics == [{"image_url": "https://example.com/img.jpg"}]
        assert article.document_type == "analysis"
        assert article.doc_metadata == {"author": "AI"}
        assert article.content_hash == "sha256hashvalue"
        assert article.version == 2

    def test_all_six_columns_in_table(self):
        expected = {
            "data_conflicts",
            "image_forensics",
            "document_type",
            "doc_metadata",
            "content_hash",
            "version",
        }
        actual = set(Article.__table__.c.keys())
        assert expected.issubset(actual), f"Missing columns: {expected - actual}"
