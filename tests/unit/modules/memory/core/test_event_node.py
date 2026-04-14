# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for EventNode data structure in memory core."""

from datetime import UTC, datetime
from typing import Any

import pytest

from modules.memory.core.event_node import EventNode


class TestEventNodeCreation:
    """Test EventNode instantiation and basic properties."""

    def test_minimal_creation(self):
        """Test creating EventNode with required fields only."""
        node = EventNode(
            id="test-1",
            content="Test event",
            timestamp=datetime.now(UTC),
        )
        assert node.id == "test-1"
        assert node.content == "Test event"
        assert isinstance(node.timestamp, datetime)
        assert node.embedding is None
        assert node.attributes == {}

    def test_full_creation(self):
        """Test creating EventNode with all fields."""
        embedding = [0.1, 0.2, 0.3]
        attributes = {"title": "Test", "source": "test_source"}
        timestamp = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

        node = EventNode(
            id="test-2",
            content="Full test event",
            timestamp=timestamp,
            embedding=embedding,
            attributes=attributes,
        )

        assert node.id == "test-2"
        assert node.content == "Full test event"
        assert node.timestamp == timestamp
        assert node.embedding == embedding
        assert node.attributes == attributes

    def test_frozen_dataclass(self):
        """Test that EventNode is immutable (frozen)."""
        node = EventNode(
            id="test-3",
            content="Immutable test",
            timestamp=datetime.now(UTC),
        )
        with pytest.raises((AttributeError, TypeError)):
            node.id = "new-id"  # type: ignore[misc]

    def test_default_empty_attributes(self):
        """Test that attributes default to empty dict."""
        node1 = EventNode(
            id="test-4a",
            content="Event 1",
            timestamp=datetime.now(UTC),
        )
        node2 = EventNode(
            id="test-4b",
            content="Event 2",
            timestamp=datetime.now(UTC),
        )
        # Each instance should have its own dict
        assert node1.attributes is not node2.attributes
        node1.attributes["key"] = "value"
        assert "key" not in node2.attributes

    def test_default_embedding_is_none(self):
        """Test that embedding defaults to None."""
        node = EventNode(
            id="test-5",
            content="No embedding",
            timestamp=datetime.now(UTC),
        )
        assert node.embedding is None


class TestEventNodeValidation:
    """Test EventNode data validation and edge cases."""

    def test_empty_id(self):
        """Test EventNode with empty ID."""
        node = EventNode(
            id="",
            content="Empty ID test",
            timestamp=datetime.now(UTC),
        )
        assert node.id == ""

    def test_empty_content(self):
        """Test EventNode with empty content."""
        node = EventNode(
            id="test-6",
            content="",
            timestamp=datetime.now(UTC),
        )
        assert node.content == ""

    def test_multiline_content(self):
        """Test EventNode with multiline content."""
        content = "Line 1\nLine 2\nLine 3"
        node = EventNode(
            id="test-7",
            content=content,
            timestamp=datetime.now(UTC),
        )
        assert node.content == content
        assert "\n" in node.content

    def test_special_characters_in_content(self):
        """Test EventNode with special characters."""
        content = "Special: <>&\"'@#$%^*()"
        node = EventNode(
            id="test-8",
            content=content,
            timestamp=datetime.now(UTC),
        )
        assert node.content == content

    def test_unicode_content(self):
        """Test EventNode with Unicode content."""
        content = "中文测试 日本語 テスト"
        node = EventNode(
            id="test-9",
            content=content,
            timestamp=datetime.now(UTC),
        )
        assert node.content == content

    def test_large_embedding(self):
        """Test EventNode with large embedding vector."""
        embedding = [0.01] * 1536  # Typical embedding size
        node = EventNode(
            id="test-10",
            content="Large embedding test",
            timestamp=datetime.now(UTC),
            embedding=embedding,
        )
        assert len(node.embedding) == 1536

    def test_complex_attributes(self):
        """Test EventNode with complex nested attributes."""
        attributes: dict[str, Any] = {
            "title": "Test",
            "metadata": {
                "source": "test",
                "tags": ["tag1", "tag2"],
                "scores": {"relevance": 0.95, "confidence": 0.87},
            },
        }
        node = EventNode(
            id="test-11",
            content="Complex attributes",
            timestamp=datetime.now(UTC),
            attributes=attributes,
        )
        assert node.attributes["metadata"]["tags"] == ["tag1", "tag2"]

    def test_timestamp_timezone_aware(self):
        """Test that timestamp preserves timezone info."""
        timestamp = datetime(2026, 6, 15, 10, 30, 0, tzinfo=UTC)
        node = EventNode(
            id="test-12",
            content="Timezone test",
            timestamp=timestamp,
        )
        assert node.timestamp.tzinfo is not None
        assert node.timestamp == timestamp


class TestEventNodeFromPipelineState:
    """Test EventNode.from_pipeline_state classmethod."""

    def test_basic_pipeline_state(self):
        """Test creating EventNode from minimal pipeline state."""
        state = {
            "article_id": "article-123",
            "cleaned": {
                "title": "Test Article",
                "content": "Test content here",
            },
        }
        node = EventNode.from_pipeline_state(state)

        assert node.id == "article-123"
        assert "Test Article" in node.content
        assert "Test content here" in node.content
        assert isinstance(node.timestamp, datetime)

    def test_pipeline_state_with_raw_data(self):
        """Test creating EventNode with raw article data."""
        from unittest.mock import MagicMock

        raw = MagicMock()
        raw.url = "https://example.com/article"
        raw.publish_time = datetime(2026, 1, 1, tzinfo=UTC)

        state = {
            "article_id": "article-456",
            "cleaned": {
                "title": "Article with URL",
                "content": "Content",
            },
            "raw": raw,
        }
        node = EventNode.from_pipeline_state(state)

        assert node.id == "article-456"
        assert node.attributes.get("source_url") == "https://example.com/article"
        assert node.timestamp == raw.publish_time

    def test_pipeline_state_with_category(self):
        """Test creating EventNode with category."""
        from unittest.mock import MagicMock

        category = MagicMock()
        category.value = "TECHNOLOGY"

        state = {
            "article_id": "article-789",
            "cleaned": {
                "title": "Tech News",
                "content": "Tech content",
            },
            "category": category,
        }
        node = EventNode.from_pipeline_state(state)

        assert node.attributes.get("category") == "TECHNOLOGY"

    def test_pipeline_state_without_title(self):
        """Test creating EventNode when title is missing."""
        state = {
            "article_id": "article-101",
            "cleaned": {
                "content": "Only content, no title",
            },
        }
        node = EventNode.from_pipeline_state(state)

        assert node.content == "Only content, no title"

    def test_pipeline_state_without_content(self):
        """Test creating EventNode when content is missing."""
        state = {
            "article_id": "article-102",
            "cleaned": {
                "title": "Only title",
            },
        }
        node = EventNode.from_pipeline_state(state)

        # When only title exists, it's used as content (title + "\n\n" + title)
        assert "Only title" in node.content

    def test_pipeline_state_with_embedding(self):
        """Test creating EventNode with embedding vectors."""
        embedding = [0.1, 0.2, 0.3, 0.4, 0.5]
        state = {
            "article_id": "article-103",
            "cleaned": {
                "title": "With embedding",
                "content": "Content",
            },
            "vectors": {
                "content": embedding,
            },
        }
        node = EventNode.from_pipeline_state(state)

        assert node.embedding == embedding

    def test_pipeline_state_without_vectors(self):
        """Test creating EventNode without vectors."""
        state = {
            "article_id": "article-104",
            "cleaned": {
                "title": "No vectors",
                "content": "Content",
            },
        }
        node = EventNode.from_pipeline_state(state)

        assert node.embedding is None

    def test_pipeline_state_empty_state(self):
        """Test creating EventNode from empty state dict."""
        state = {}
        node = EventNode.from_pipeline_state(state)

        assert node.id == ""
        assert node.content == ""
        assert isinstance(node.timestamp, datetime)

    def test_pipeline_state_default_timestamp(self):
        """Test that missing timestamp defaults to now."""
        state = {
            "article_id": "article-105",
            "cleaned": {
                "title": "No timestamp",
                "content": "Content",
            },
        }
        node = EventNode.from_pipeline_state(state)

        # Should be recent (within last minute)
        time_diff = datetime.now(UTC) - node.timestamp
        assert time_diff.total_seconds() < 60

    def test_pipeline_state_with_raw_no_url(self):
        """Test creating EventNode with raw data but no URL."""
        from unittest.mock import MagicMock

        raw = MagicMock()
        raw.url = None
        raw.publish_time = None

        state = {
            "article_id": "article-106",
            "cleaned": {
                "title": "No URL",
                "content": "Content",
            },
            "raw": raw,
        }
        node = EventNode.from_pipeline_state(state)

        assert "source_url" not in node.attributes

    def test_pipeline_state_category_as_string(self):
        """Test creating EventNode with category as string (not enum)."""
        state = {
            "article_id": "article-107",
            "cleaned": {
                "title": "String category",
                "content": "Content",
            },
            "category": "POLITICS",
        }
        node = EventNode.from_pipeline_state(state)

        assert node.attributes.get("category") == "POLITICS"

    def test_pipeline_state_title_and_content_combination(self):
        """Test that title and content are properly combined."""
        state = {
            "article_id": "article-108",
            "cleaned": {
                "title": "Test Title",
                "content": "Test Content",
            },
        }
        node = EventNode.from_pipeline_state(state)

        expected = "Test Title\n\nTest Content"
        assert node.content == expected
