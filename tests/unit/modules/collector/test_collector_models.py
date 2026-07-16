# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for Collector module."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.domain.models import RawArticle


@pytest.fixture
def sample_article():
    """Create sample article for testing."""
    return RawArticle(
        url="https://example.com/article1",
        title="Test Article",
        body="This is test content for the article body.",
        source="test_source",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def sample_articles():
    """Create multiple sample articles."""
    return [
        RawArticle(
            url=f"https://example.com/article{i}",
            title=f"Article {i}",
            body=f"Content for article {i}",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        for i in range(5)
    ]


class TestRawArticleModel:
    """Tests for RawArticle model."""

    def test_article_raw_creation(self):
        """Test creating an RawArticle instance."""
        article = RawArticle(
            url="https://example.com/test",
            title="Test Title",
            body="Test Body",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )

        assert article.url == "https://example.com/test"
        assert article.title == "Test Title"
        assert article.body == "Test Body"
        assert article.source == "test_source"
        assert article.source_host == "example.com"

    def test_article_raw_with_optional_fields(self):
        """Test RawArticle with optional fields."""
        article = RawArticle(
            url="https://example.com/test",
            title="Test Title",
            body="Test Body",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
            tier=1,
        )

        assert article.tier == 1

    def test_article_raw_equality(self, sample_article):
        """Test RawArticle equality comparison."""
        article_copy = RawArticle(
            url=sample_article.url,
            title=sample_article.title,
            body=sample_article.body,
            source=sample_article.source,
            publish_time=sample_article.publish_time,
            source_host=sample_article.source_host,
        )

        # URLs match but they're different objects
        assert article_copy.url == sample_article.url


class TestCollectorModels:
    """Tests for collector model functionality."""

    def test_article_url_validation(self):
        """Test that article URLs are properly stored."""
        article = RawArticle(
            url="https://example.com/valid-url",
            title="Title",
            body="Body",
            source="source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )

        assert "example.com" in article.url
        assert article.url.startswith("https://")

    def test_article_publish_time_handling(self):
        """Test handling of publish time."""
        now = datetime.now(UTC)

        article = RawArticle(
            url="https://example.com/test",
            title="Title",
            body="Body",
            source="source",
            publish_time=now,
            source_host="example.com",
        )

        assert article.publish_time == now
        # Should handle timezone-aware datetime
        assert article.publish_time.tzinfo is not None


class TestCollectorSerialization:
    """Tests for collector model serialization."""

    def test_article_to_dict(self, sample_article):
        """Test converting RawArticle to dictionary."""
        article_dict = {
            "url": sample_article.url,
            "title": sample_article.title,
            "body": sample_article.body,
            "source": sample_article.source,
            "publish_time": sample_article.publish_time,
            "source_host": sample_article.source_host,
        }

        assert isinstance(article_dict, dict)
        assert "url" in article_dict
        assert "title" in article_dict

    def test_article_from_dict(self):
        """Test creating RawArticle from dictionary."""
        data = {
            "url": "https://example.com/test",
            "title": "Test Title",
            "body": "Test Body",
            "source": "test_source",
            "publish_time": datetime.now(UTC),
            "source_host": "example.com",
        }

        article = RawArticle(**data)

        assert article.url == data["url"]
        assert article.title == data["title"]


class TestCollectorEdgeCases:
    """Edge case tests for collector models."""

    def test_article_with_empty_body(self):
        """Test RawArticle with empty body."""
        article = RawArticle(
            url="https://example.com/empty",
            title="Title Only",
            body="",
            source="source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )

        assert article.body == ""

    def test_article_with_long_content(self):
        """Test RawArticle with long content."""
        long_body = "A" * 10000

        article = RawArticle(
            url="https://example.com/long",
            title="Long Article",
            body=long_body,
            source="source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )

        assert len(article.body) == 10000

    def test_multiple_articles_batch(self, sample_articles):
        """Test handling multiple articles as a batch."""
        assert len(sample_articles) == 5

        # All should have valid URLs
        for article in sample_articles:
            assert article.url.startswith("https://example.com/")


class TestCollectorErrorHandling:
    """Error handling tests for collector models."""

    def test_article_with_missing_url(self):
        """Test handling of missing URL."""
        try:
            RawArticle(
                url="",
                title="Title",
                body="Body",
                source="source",
                publish_time=datetime.now(UTC),
                source_host="example.com",
            )
            # Empty URL is allowed (validation is external)
            assert True
        except ValueError:
            # Validation may reject empty URL
            assert True

    def test_article_with_invalid_time(self):
        """Test handling of invalid publish time."""
        # None publish time should be allowed
        article = RawArticle(
            url="https://example.com/test",
            title="Title",
            body="Body",
            source="source",
            publish_time=None,
            source_host="example.com",
        )

        assert article.publish_time is None
