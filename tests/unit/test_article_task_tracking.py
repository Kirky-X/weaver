"""Unit tests for Article model task_id field."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.db.models import Article, PersistStatus


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
        assert PersistStatus.is_valid_transition(
            PersistStatus.PENDING, PersistStatus.PROCESSING
        )

    def test_valid_transition_processing_to_pg_done(self):
        """Test valid transition: PROCESSING -> PG_DONE."""
        assert PersistStatus.is_valid_transition(
            PersistStatus.PROCESSING, PersistStatus.PG_DONE
        )

    def test_valid_transition_pg_done_to_neo4j_done(self):
        """Test valid transition: PG_DONE -> NEO4J_DONE."""
        assert PersistStatus.is_valid_transition(
            PersistStatus.PG_DONE, PersistStatus.NEO4J_DONE
        )

    def test_valid_transition_any_to_failed(self):
        """Test valid transition to FAILED from any state."""
        assert PersistStatus.is_valid_transition(
            PersistStatus.PENDING, PersistStatus.FAILED
        )
        assert PersistStatus.is_valid_transition(
            PersistStatus.PROCESSING, PersistStatus.FAILED
        )
        assert PersistStatus.is_valid_transition(
            PersistStatus.PG_DONE, PersistStatus.FAILED
        )

    def test_invalid_transition_pending_to_neo4j_done(self):
        """Test invalid transition: PENDING -> NEO4J_DONE."""
        assert not PersistStatus.is_valid_transition(
            PersistStatus.PENDING, PersistStatus.NEO4J_DONE
        )

    def test_invalid_transition_neo4j_done_to_any(self):
        """Test invalid transition from NEO4J_DONE (terminal state)."""
        assert not PersistStatus.is_valid_transition(
            PersistStatus.NEO4J_DONE, PersistStatus.PENDING
        )
        assert not PersistStatus.is_valid_transition(
            PersistStatus.NEO4J_DONE, PersistStatus.PROCESSING
        )

    def test_idempotent_same_status(self):
        """Test that staying in the same status is allowed (idempotent)."""
        assert PersistStatus.is_valid_transition(
            PersistStatus.PENDING, PersistStatus.PENDING
        )
        assert PersistStatus.is_valid_transition(
            PersistStatus.PROCESSING, PersistStatus.PROCESSING
        )
        assert PersistStatus.is_valid_transition(
            PersistStatus.PG_DONE, PersistStatus.PG_DONE
        )
