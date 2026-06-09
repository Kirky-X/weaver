from datetime import datetime
from uuid import UUID, uuid4

import pytest

from core.models.shared import ArticleView


class TestArticleView:
    def test_model_exists(self):
        assert ArticleView is not None

    def test_uses_pydantic_v2_config_dict(self):
        assert ArticleView.model_config.get("from_attributes") is True

    def test_has_all_required_fields(self):
        article_id = uuid4()
        now = datetime.now()
        article = ArticleView(
            id=article_id,
            source_url="https://example.com/article",
            title="Test Article",
            body="Test body content",
            publish_time=now,
            created_at=now,
            updated_at=now,
        )
        assert article.id == article_id
        assert article.source_url == "https://example.com/article"
        assert article.title == "Test Article"
        assert article.body == "Test body content"
        assert article.publish_time == now
        assert article.created_at == now
        assert article.updated_at == now

    def test_default_values(self):
        article_id = uuid4()
        article = ArticleView(
            id=article_id,
            source_url="https://example.com/article",
            title="Test Article",
        )
        assert article.is_news is False
        assert article.document_type == "news"
        assert article.version == 1
        assert article.persist_status == "pending"
        assert article.data_conflicts == []
        assert article.image_forensics == []
        assert article.doc_metadata == {}
        assert article.source_host is None
        assert article.category is None
        assert article.language is None
        assert article.score is None

    def test_model_validate_from_orm_dict(self):
        article_id = uuid4()
        data = {
            "id": article_id,
            "source_url": "https://example.com/article",
            "source_host": "example.com",
            "is_news": True,
            "title": "Test Article",
            "body": "Body text",
            "category": "tech",
            "language": "en",
            "region": "US",
            "summary": "A test article",
            "subjects": ["tech", "AI"],
            "key_data": ["data1"],
            "impact": "high",
            "has_data": True,
            "score": 0.95,
            "quality_score": 0.85,
            "data_conflicts": [],
            "image_forensics": [],
            "document_type": "news",
            "doc_metadata": {"source": "test"},
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
        article = ArticleView.model_validate(data)
        assert article.id == article_id
        assert article.source_host == "example.com"
        assert article.is_news is True
        assert article.category == "tech"
        assert article.sentiment == "positive"
        assert article.persist_status == "completed"

    def test_model_validate_from_orm_instance(self):
        article_id = uuid4()

        class FakeORMRow:
            id = article_id
            source_url = "https://example.com/article"
            source_host = "example.com"
            is_news = True
            title = "Test Article"
            body = "Body text"
            category = "tech"
            language = "en"
            region = "US"
            summary = "A test article"
            subjects = ["tech", "AI"]
            key_data = ["data1"]
            impact = "high"
            has_data = True
            score = 0.95
            quality_score = 0.85
            data_conflicts = []
            image_forensics = []
            document_type = "news"
            doc_metadata = {}
            content_hash = "abc123"
            version = 1
            sentiment = "positive"
            sentiment_score = 0.8
            primary_emotion = "joy"
            emotion_targets = ["target1"]
            credibility_score = 0.9
            source_credibility = 0.85
            cross_verification = 0.75
            content_check_score = 0.88
            credibility_flags = []
            persist_status = "completed"
            publish_time = None
            created_at = None
            updated_at = None

        article = ArticleView.model_validate(FakeORMRow())
        assert article.id == article_id
        assert article.title == "Test Article"
        assert article.category == "tech"

    def test_serialize_to_dict(self):
        article_id = uuid4()
        article = ArticleView(
            id=article_id,
            source_url="https://example.com/article",
            title="Test",
        )
        data = article.model_dump()
        assert isinstance(data, dict)
        assert data["id"] == article_id
        assert data["title"] == "Test"
        assert data["source_url"] == "https://example.com/article"
        assert data["persist_status"] == "pending"

    def test_optional_fields_default_to_none(self):
        article_id = uuid4()
        article = ArticleView(
            id=article_id,
            source_url="https://example.com/article",
            title="Test",
        )
        assert article.body is None
        assert article.summary is None
        assert article.subjects is None
        assert article.sentiment is None
        assert article.credibility_score is None
