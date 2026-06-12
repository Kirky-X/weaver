from datetime import datetime
from uuid import UUID, uuid4

import pytest

from core.models.shared import ArticleView
from tests.unit.core.models._base import ViewModelTestBase

# Fields defined in ADD §1.5.1 that SHALL be present
REQUIRED_FIELDS = {
    "id",
    "title",
    "source_url",
    "publish_time",
    "score",
    "category",
    "sentiment_score",
    "summary",
    "verified_by_sources",
}

# Fields explicitly removed per spec
REMOVED_FIELDS = {
    "is_news",
    "impact",
    "has_data",
    "image_forensics",
    "document_type",
    "doc_metadata",
    "content_hash",
    "version",
    "primary_emotion",
    "source_credibility",
    "content_check_score",
    "credibility_flags",
}


class TestArticleViewAlignment(ViewModelTestBase):
    """Tests for ArticleView field alignment with ADD §1.5.1."""

    model_class = ArticleView
    required_fields = REQUIRED_FIELDS
    removed_fields = REMOVED_FIELDS

    def _create_minimal_instance(self):
        return ArticleView(
            id=uuid4(),
            source_url="https://example.com/article",
            title="Test Article",
        )

    def test_verified_by_sources_field_exists(self):
        article = self._create_minimal_instance()
        assert hasattr(article, "verified_by_sources")
        assert article.verified_by_sources is False

    def test_verified_by_sources_can_be_set(self):
        article = ArticleView(
            id=uuid4(),
            source_url="https://example.com/article",
            title="Test Article",
            verified_by_sources=True,
        )
        assert article.verified_by_sources is True

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
        article = self._create_minimal_instance()
        assert article.verified_by_sources is False
        assert article.data_conflicts == []
        assert article.source_host is None
        assert article.category is None
        assert article.language is None
        assert article.score is None
        assert article.sentiment is None
        assert article.sentiment_score is None
        assert article.credibility_score is None

    def test_model_validate_from_dict(self):
        article_id = uuid4()
        data = {
            "id": article_id,
            "source_url": "https://example.com/article",
            "source_host": "example.com",
            "title": "Test Article",
            "body": "Body text",
            "category": "tech",
            "language": "en",
            "region": "US",
            "summary": "A test article",
            "subjects": ["tech", "AI"],
            "key_data": ["data1"],
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
        article = ArticleView.model_validate(data)
        assert article.id == article_id
        assert article.source_host == "example.com"
        assert article.category == "tech"
        assert article.sentiment == "positive"
        assert article.persist_status == "completed"
        assert article.verified_by_sources is True

    def test_model_validate_from_orm_instance(self):
        article_id = uuid4()

        class FakeORMRow:
            id = article_id
            source_url = "https://example.com/article"
            source_host = "example.com"
            title = "Test Article"
            body = "Body text"
            category = "tech"
            language = "en"
            region = "US"
            summary = "A test article"
            subjects = ["tech", "AI"]
            key_data = ["data1"]
            score = 0.95
            quality_score = 0.85
            data_conflicts = []
            sentiment = "positive"
            sentiment_score = 0.8
            emotion_targets = ["target1"]
            credibility_score = 0.9
            cross_verification = 0.75
            persist_status = "completed"
            verified_by_sources = True
            publish_time = None
            created_at = None
            updated_at = None

        article = ArticleView.model_validate(FakeORMRow())
        assert article.id == article_id
        assert article.title == "Test Article"
        assert article.category == "tech"
        assert article.verified_by_sources is True

    def test_serialize_to_dict(self):
        """Override to add specific field assertions."""
        article = self._create_minimal_instance()
        data = article.model_dump()
        assert isinstance(data, dict)
        assert data["title"] == "Test Article"
        assert data["source_url"] == "https://example.com/article"
        assert data["persist_status"] == "pending"
        assert data["verified_by_sources"] is False
