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
            "is_news": True,
            "title": "Test Article",
            "body": "Test body content",
            "category": "tech",
            "language": "en",
            "region": "US",
            "summary": "A test article summary",
            "subjects": ["tech", "AI"],
            "key_data": ["key1", "key2"],
            "impact": "high",
            "has_data": True,
            "score": 0.95,
            "quality_score": 0.85,
            "data_conflicts": [],
            "image_forensics": [],
            "document_type": "news",
            "doc_metadata": {},
            "content_hash": "abc123",
            "version": 2,
            "sentiment": "positive",
            "sentiment_score": 0.8,
            "primary_emotion": "joy",
            "emotion_targets": ["target1"],
            "credibility_score": 0.9,
            "source_credibility": 0.85,
            "cross_verification": 0.75,
            "content_check_score": 0.88,
            "credibility_flags": [],
            "persist_status": "completed",
            "publish_time": None,
            "created_at": None,
            "updated_at": None,
        }
        result = PostgresArticleMapper.to_view(orm_data)
        assert isinstance(result, ArticleView)
        assert result.id == article_id
        assert result.title == "Test Article"
        assert result.category == "tech"
        assert result.score == 0.95

    def test_to_view_maps_all_fields_correctly(self):
        article_id = uuid4()
        orm_data = {
            "id": article_id,
            "source_url": "https://example.com/article",
            "title": "Test Article",
        }
        result = PostgresArticleMapper.to_view(orm_data)
        assert result.source_url == "https://example.com/article"
        assert result.is_news is False
        assert result.persist_status == "pending"

    def test_to_view_with_orm_instance(self):
        article_id = uuid4()

        class FakeORMRow:
            id = article_id
            source_url = "https://example.com/article"
            source_host = "example.com"
            is_news = False
            title = "ORM Article"
            body = "Body"
            category = "science"
            language = "en"
            region = "UK"
            summary = None
            subjects = None
            key_data = None
            impact = None
            has_data = None
            score = None
            quality_score = None
            data_conflicts = []
            image_forensics = []
            document_type = "news"
            doc_metadata = {}
            content_hash = None
            version = 1
            sentiment = None
            sentiment_score = None
            primary_emotion = None
            emotion_targets = None
            credibility_score = None
            source_credibility = None
            cross_verification = None
            content_check_score = None
            credibility_flags = None
            persist_status = "pending"
            publish_time = None
            created_at = None
            updated_at = None

        result = PostgresArticleMapper.to_view(FakeORMRow())
        assert isinstance(result, ArticleView)
        assert result.title == "ORM Article"
        assert result.category == "science"
        assert result.source_host == "example.com"
