# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pytest configuration and shared fixtures for pipeline tests."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.domain.models import RawArticle


@pytest.fixture
def sample_raw():
    """Create sample RawArticle for pipeline node tests."""
    return RawArticle(
        url="https://example.com/test-article",
        title="Test Article Title",
        body="Test article body content.",
        source="test_source",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_budget():
    """Mock token budget manager for pipeline tests."""
    budget = MagicMock()
    budget.truncate = MagicMock(
        side_effect=lambda text, cp: text[:2000] if len(text) > 2000 else text
    )
    return budget


@pytest.fixture
def mock_prompt_loader():
    """Mock prompt loader for pipeline tests."""
    loader = MagicMock()
    loader.get_version = MagicMock(return_value="1.0.0")
    return loader


@pytest.fixture
def mock_event_bus():
    """Mock event bus for pipeline tests."""
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def sample_article_raw(sample_raw):
    """Alias for sample_raw for backward compatibility with root conftest.py."""
    return sample_raw
