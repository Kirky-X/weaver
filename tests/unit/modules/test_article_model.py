# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Article model task_id field."""

from __future__ import annotations

import uuid

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
        """Test valid transition: PROCESSING -> STORED."""

    assert PersistStatus.is_valid_transition(PersistStatus.PROCESSING, PersistStatus.STORED)

    def test_invalid_transition_processing_to_complete(self):
        assert not PersistStatus.is_valid_transition(
            PersistStatus.PROCESSING, PersistStatus.COMPLETE
        )

    def test_valid_transition_complete_to_complete(self):
        assert PersistStatus.is_valid_transition(PersistStatus.COMPLETE, PersistStatus.COMPLETE)

    def test_valid_transition_stored_to_enriching(self):
        assert PersistStatus.is_valid_transition(PersistStatus.STORED, PersistStatus.ENRICHING)

    def test_valid_transition_enriching_to_complete(self):
        assert PersistStatus.is_valid_transition(PersistStatus.ENRICHING, PersistStatus.COMPLETE)

    def test_valid_transition_stored_to_failed(self):
        assert PersistStatus.is_valid_transition(PersistStatus.STORED, PersistStatus.FAILED)

    def test_invalid_transition_stored_to_pending(self):
        assert not PersistStatus.is_valid_transition(PersistStatus.STORED, PersistStatus.PENDING)

    def test_invalid_transition_complete_to_pending(self):
        assert not PersistStatus.is_valid_transition(PersistStatus.COMPLETE, PersistStatus.PENDING)

    def test_invalid_transition_complete_to_processing(self):
        assert not PersistStatus.is_valid_transition(
            PersistStatus.COMPLETE, PersistStatus.PROCESSING
        )

    def test_valid_transition_stored_to_stored(self):
        assert PersistStatus.is_valid_transition(PersistStatus.STORED, PersistStatus.STORED)
