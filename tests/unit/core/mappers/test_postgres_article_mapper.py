from uuid import uuid4

import pytest

from core.mappers.postgres_article_mapper import PostgresArticleMapper
from core.models.shared import ArticleView


class TestPostgresArticleMapper:
    def test_to_view_returns_article_view(self):
        article_id = uuid4()
        orm_data = {
            "id": article_id,
            "source_url": "https://example.com/article",
            "source_host": "example.com",
            "title": "Test Article",
            "body": "Test body content",
            "category": "tech",
            "language": "en",
            "region": "US",
            "summary": "A test article summary",
            "subjects": ["tech", "AI"],
            "key_data": ["key1", "key2"],
            "score": 0.95,
            "quality_score": 0.85,
            "data_conflicts": [],
            "sentiment": "positive",
            "sentiment_score": 0.8,
            "emotion_targets": ["target1"],
            "credibility_score": 0.9,
            "cross_verification": 0.75,
            "persist_status": "completed",
            "verified_by_sources": True,
            "publish_time": None,
            "created_at": None,
            "updated_at": None,
        }
        result = PostgresArticleMapper().to_view(orm_data)
        assert isinstance(result, ArticleView)
        assert result.id == article_id
        assert result.title == "Test Article"
        assert result.category == "tech"
        assert result.score == 0.95
        assert result.verified_by_sources == 1

    def test_to_view_maps_all_fields_correctly(self):
        article_id = uuid4()
        orm_data = {
            "id": article_id,
            "source_url": "https://example.com/article",
            "title": "Test Article",
        }
        result = PostgresArticleMapper().to_view(orm_data)
        assert result.source_url == "https://example.com/article"
        assert result.persist_status == "pending"
        assert result.verified_by_sources == 0

    def test_to_view_with_orm_instance(self):
        article_id = uuid4()

        class FakeORMRow:
            id = article_id
            source_url = "https://example.com/article"
            source_host = "example.com"
            title = "ORM Article"
            body = "Body"
            category = "science"
            language = "en"
            region = "UK"
            summary = None
            subjects = None
            key_data = None
            score = None
            quality_score = None
            data_conflicts = []
            sentiment = None
            sentiment_score = None
            emotion_targets = None
            credibility_score = None
            cross_verification = None
            persist_status = "pending"
            verified_by_sources = False
            publish_time = None
            created_at = None
            updated_at = None

        result = PostgresArticleMapper().to_view(FakeORMRow())
        assert isinstance(result, ArticleView)
        assert result.title == "ORM Article"
        assert result.category == "science"
        assert result.source_host == "example.com"

    def test_to_view_converts_score_string_to_float(self):
        """Mapper SHALL convert string score to float."""
        article_id = uuid4()
        orm_data = {
            "id": article_id,
            "source_url": "https://example.com/article",
            "title": "Test",
            "score": "0.85",
        }
        result = PostgresArticleMapper().to_view(orm_data)
        assert result.score == 0.85
        assert isinstance(result.score, float)

    def test_to_view_handles_missing_verified_by_sources(self):
        """Mapper SHALL default verified_by_sources to 0 when missing."""
        article_id = uuid4()
        orm_data = {
            "id": article_id,
            "source_url": "https://example.com/article",
            "title": "Test",
        }
        result = PostgresArticleMapper().to_view(orm_data)
        assert result.verified_by_sources == 0

    def test_to_view_ignores_removed_fields(self):
        """Mapper SHALL ignore fields that have been removed from ArticleView."""
        article_id = uuid4()
        orm_data = {
            "id": article_id,
            "source_url": "https://example.com/article",
            "title": "Test",
            "is_news": True,
            "impact": "high",
            "document_type": "report",
        }
        result = PostgresArticleMapper().to_view(orm_data)
        assert isinstance(result, ArticleView)
        assert result.title == "Test"
