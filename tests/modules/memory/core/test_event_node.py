# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for EventNode data model."""

from datetime import UTC, datetime

import pytest

from modules.memory.core.event_node import EventNode


@pytest.mark.unit
def test_event_node_creation():
    """Test basic EventNode creation."""
    now = datetime.now(UTC)
    node = EventNode(
        id="test-123",
        content="Test event content",
        timestamp=now,
    )

    assert node.id == "test-123"
    assert node.content == "Test event content"
    assert node.timestamp == now
    assert node.embedding is None
    assert node.attributes == {}


@pytest.mark.unit
def test_event_node_with_embedding():
    """Test EventNode with embedding."""
    node = EventNode(
        id="test-456",
        content="Content with embedding",
        timestamp=datetime.now(UTC),
        embedding=[0.1, 0.2, 0.3],
    )

    assert node.embedding == [0.1, 0.2, 0.3]


@pytest.mark.unit
def test_event_node_with_attributes():
    """Test EventNode with custom attributes."""
    node = EventNode(
        id="test-789",
        content="Content with attributes",
        timestamp=datetime.now(UTC),
        attributes={
            "title": "Test Title",
            "source_url": "https://example.com",
            "category": "news",
        },
    )

    assert node.attributes["title"] == "Test Title"
    assert node.attributes["source_url"] == "https://example.com"
    assert node.attributes["category"] == "news"


@pytest.mark.unit
def test_event_node_immutable():
    """Test EventNode is immutable (frozen dataclass)."""
    node = EventNode(
        id="test-immutable",
        content="Immutable content",
        timestamp=datetime.now(UTC),
    )

    with pytest.raises(AttributeError):
        node.content = "Modified content"


@pytest.mark.unit
def test_event_node_from_pipeline_state():
    """Test creating EventNode from pipeline state dict."""

    class MockRaw:
        publish_time = datetime(2026, 4, 2, 12, 0, 0, tzinfo=UTC)
        url = "https://example.com/article"

    state = {
        "article_id": "article-001",
        "cleaned": {
            "title": "Test Article",
            "content": "Article content here",
        },
        "raw": MockRaw(),
        "vectors": {
            "content": [0.1] * 384,
        },
        "category": "technology",
    }

    node = EventNode.from_pipeline_state(state)

    assert node.id == "article-001"
    assert "Test Article" in node.content
    assert node.timestamp == datetime(2026, 4, 2, 12, 0, 0, tzinfo=UTC)
    assert node.embedding == [0.1] * 384
    assert node.attributes["source_url"] == "https://example.com/article"
    assert node.attributes["category"] == "technology"
