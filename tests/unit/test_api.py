"""Unit tests for API endpoints."""

import pytest
import uuid
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from fastapi.testclient import TestClient
from fastapi import HTTPException


class TestAuthMiddleware:
    """Tests for authentication middleware."""

    @pytest.mark.asyncio
    async def test_verify_api_key_missing(self):
        """Test verify_api_key raises 401 when key is missing."""
        from api.middleware.auth import verify_api_key

        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(key=None)
        assert exc_info.value.status_code == 401
        assert "Missing API key" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verify_api_key_invalid(self):
        """Test verify_api_key raises 403 for invalid key."""
        from api.middleware.auth import verify_api_key

        mock_settings = MagicMock()
        mock_settings.api.api_key = "valid-key"

        with patch("container.get_settings", return_value=mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(key="invalid-key")
            assert exc_info.value.status_code == 403
            assert "Invalid API Key" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verify_api_key_valid(self):
        """Test verify_api_key returns key when valid."""
        from api.middleware.auth import verify_api_key

        mock_settings = MagicMock()
        mock_settings.api.api_key = "valid-key"

        with patch("container.get_settings", return_value=mock_settings):
            result = await verify_api_key(key="valid-key")
            assert result == "valid-key"

    def test_api_key_header_exists(self):
        """Test API key header is defined."""
        from api.middleware.auth import api_key_header

        assert api_key_header is not None
        assert api_key_header.model.name == "X-API-Key"


class TestSourcesEndpoint:
    """Tests for sources endpoints."""

    def test_source_response_model(self):
        """Test SourceResponse model."""
        from api.endpoints.sources import SourceResponse

        response = SourceResponse(
            id="test",
            name="Test Source",
            url="https://example.com/feed.xml",
            source_type="rss",
            enabled=True,
            interval_minutes=30,
            per_host_concurrency=2,
        )
        assert response.id == "test"
        assert response.name == "Test Source"

    def test_source_create_request_model(self):
        """Test SourceCreateRequest model validation."""
        from api.endpoints.sources import SourceCreateRequest

        request = SourceCreateRequest(
            id="new_source",
            name="New Source",
            url="https://example.com/new.xml",
        )
        assert request.id == "new_source"
        assert request.enabled is True

    def test_source_update_request_model(self):
        """Test SourceUpdateRequest model validation."""
        from api.endpoints.sources import SourceUpdateRequest

        request = SourceUpdateRequest(
            name="Updated Name",
            enabled=False,
            interval_minutes=60,
        )
        assert request.name == "Updated Name"
        assert request.enabled is False
        assert request.url is None

    def test_source_response_from_config(self):
        """Test SourceResponse.from_config factory method."""
        from api.endpoints.sources import SourceResponse
        from modules.source.models import SourceConfig

        config = SourceConfig(
            id="test-id",
            name="Test",
            url="https://test.com/feed.xml",
            source_type="rss",
            enabled=True,
            interval_minutes=30,
            per_host_concurrency=2,
        )
        response = SourceResponse.from_config(config)
        assert response.id == "test-id"
        assert response.name == "Test"

    @pytest.mark.asyncio
    async def test_list_sources_endpoint(self):
        """Test GET /sources endpoint."""
        from api.endpoints.sources import list_sources, get_source_registry

        mock_registry = MagicMock()
        mock_config = MagicMock()
        mock_config.id = "source-1"
        mock_config.name = "Test Source"
        mock_config.url = "https://test.com/feed.xml"
        mock_config.source_type = "rss"
        mock_config.enabled = True
        mock_config.interval_minutes = 30
        mock_config.per_host_concurrency = 2
        mock_config.last_crawl_time = None
        mock_registry.list_sources.return_value = [mock_config]

        with patch("api.endpoints.sources.get_source_registry", return_value=mock_registry):
            result = await list_sources(
                enabled_only=True,
                _="test-key",
                registry=mock_registry,
            )
            assert len(result) == 1
            assert result[0].id == "source-1"

    @pytest.mark.asyncio
    async def test_create_source_endpoint_success(self):
        """Test POST /sources endpoint creates new source."""
        from api.endpoints.sources import create_source, SourceCreateRequest

        mock_registry = MagicMock()
        mock_registry.get_source.return_value = None

        request = SourceCreateRequest(
            id="new-source",
            name="New Source",
            url="https://new.com/feed.xml",
        )

        result = await create_source(
            request=request,
            _="test-key",
            registry=mock_registry,
        )
        assert result.id == "new-source"
        mock_registry.add_source.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_source_endpoint_conflict(self):
        """Test POST /sources returns 409 for existing source."""
        from api.endpoints.sources import create_source, SourceCreateRequest

        mock_registry = MagicMock()
        mock_registry.get_source.return_value = MagicMock()

        request = SourceCreateRequest(
            id="existing-source",
            name="Existing",
            url="https://existing.com/feed.xml",
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_source(
                request=request,
                _="test-key",
                registry=mock_registry,
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_update_source_endpoint_success(self):
        """Test PUT /sources/{source_id} endpoint."""
        from api.endpoints.sources import update_source, SourceUpdateRequest

        mock_existing = MagicMock()
        mock_existing.id = "source-1"
        mock_existing.name = "Old Name"
        mock_existing.url = "https://old.com/feed.xml"
        mock_existing.source_type = "rss"
        mock_existing.enabled = True
        mock_existing.interval_minutes = 30
        mock_existing.per_host_concurrency = 2
        mock_existing.last_crawl_time = None

        mock_registry = MagicMock()
        mock_registry.get_source.return_value = mock_existing

        request = SourceUpdateRequest(name="New Name", enabled=False)

        result = await update_source(
            source_id="source-1",
            request=request,
            _="test-key",
            registry=mock_registry,
        )
        assert mock_existing.name == "New Name"
        assert mock_existing.enabled is False
        mock_registry.add_source.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_source_endpoint_not_found(self):
        """Test PUT /sources/{source_id} returns 404 for missing source."""
        from api.endpoints.sources import update_source, SourceUpdateRequest

        mock_registry = MagicMock()
        mock_registry.get_source.return_value = None

        request = SourceUpdateRequest(name="New Name")

        with pytest.raises(HTTPException) as exc_info:
            await update_source(
                source_id="missing-source",
                request=request,
                _="test-key",
                registry=mock_registry,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_source_endpoint_success(self):
        """Test DELETE /sources/{source_id} endpoint."""
        from api.endpoints.sources import delete_source

        mock_registry = MagicMock()
        mock_registry.get_source.return_value = MagicMock()

        await delete_source(
            source_id="source-1",
            _="test-key",
            registry=mock_registry,
        )
        mock_registry.remove_source.assert_called_once_with("source-1")

    @pytest.mark.asyncio
    async def test_delete_source_endpoint_not_found(self):
        """Test DELETE /sources/{source_id} returns 404 for missing source."""
        from api.endpoints.sources import delete_source

        mock_registry = MagicMock()
        mock_registry.get_source.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await delete_source(
                source_id="missing-source",
                _="test-key",
                registry=mock_registry,
            )
        assert exc_info.value.status_code == 404

    def test_get_source_registry_not_initialized(self):
        """Test get_source_registry raises 503 when not initialized."""
        from api.endpoints.sources import get_source_registry

        with patch("api.endpoints.sources._source_registry", None):
            with pytest.raises(HTTPException) as exc_info:
                get_source_registry()
            assert exc_info.value.status_code == 503


class TestPipelineEndpoint:
    """Tests for pipeline endpoints."""

    def test_trigger_request_model(self):
        """Test TriggerRequest model."""
        from api.endpoints.pipeline import TriggerRequest

        request = TriggerRequest()
        assert request.source_id is None
        assert request.force is False

    def test_trigger_request_with_values(self):
        """Test TriggerRequest with custom values."""
        from api.endpoints.pipeline import TriggerRequest

        request = TriggerRequest(source_id="source-1", force=True)
        assert request.source_id == "source-1"
        assert request.force is True

    def test_trigger_response_model(self):
        """Test TriggerResponse model."""
        from api.endpoints.pipeline import TriggerResponse

        response = TriggerResponse(
            task_id="test-123",
            status="queued",
            queued_at="2024-01-01T00:00:00",
        )
        assert response.task_id == "test-123"
        assert response.status == "queued"

    def test_task_status_response_model(self):
        """Test TaskStatusResponse model."""
        from api.endpoints.pipeline import TaskStatusResponse

        response = TaskStatusResponse(
            task_id="task-123",
            status="completed",
            source_id="source-1",
            queued_at="2024-01-01T00:00:00",
            started_at="2024-01-01T00:00:01",
            completed_at="2024-01-01T00:01:00",
            progress=100,
            total=100,
        )
        assert response.task_id == "task-123"
        assert response.status == "completed"
        assert response.progress == 100

    @pytest.mark.asyncio
    async def test_trigger_pipeline_specific_source(self):
        """Test POST /pipeline/trigger with specific source."""
        from api.endpoints.pipeline import trigger_pipeline, TriggerRequest

        mock_redis = MagicMock()
        mock_redis.client = MagicMock()
        mock_redis.client.hset = AsyncMock()

        mock_scheduler = MagicMock()
        mock_scheduler.trigger_now = AsyncMock()

        request = TriggerRequest(source_id="source-1")

        with patch("api.endpoints.pipeline.uuid.uuid4", return_value=uuid.UUID("12345678-1234-5678-1234-567812345678")):
            result = await trigger_pipeline(
                request=request,
                _="test-key",
                redis=mock_redis,
                scheduler=mock_scheduler,
            )

        assert result.task_id == "12345678-1234-5678-1234-567812345678"
        mock_scheduler.trigger_now.assert_called_once_with("source-1")

    @pytest.mark.asyncio
    async def test_trigger_pipeline_all_sources(self):
        """Test POST /pipeline/trigger for all enabled sources."""
        from api.endpoints.pipeline import trigger_pipeline, TriggerRequest

        mock_redis = MagicMock()
        mock_redis.client = MagicMock()
        mock_redis.client.hset = AsyncMock()

        mock_source1 = MagicMock()
        mock_source1.id = "source-1"
        mock_source2 = MagicMock()
        mock_source2.id = "source-2"

        mock_scheduler = MagicMock()
        mock_scheduler.trigger_now = AsyncMock()
        mock_scheduler._registry = MagicMock()
        mock_scheduler._registry.list_sources.return_value = [mock_source1, mock_source2]

        request = TriggerRequest()

        with patch("api.endpoints.pipeline.uuid.uuid4", return_value=uuid.UUID("12345678-1234-5678-1234-567812345678")):
            result = await trigger_pipeline(
                request=request,
                _="test-key",
                redis=mock_redis,
                scheduler=mock_scheduler,
            )

        assert mock_scheduler.trigger_now.call_count == 2

    @pytest.mark.asyncio
    async def test_trigger_pipeline_failure(self):
        """Test POST /pipeline/trigger handles errors."""
        from api.endpoints.pipeline import trigger_pipeline, TriggerRequest

        mock_redis = MagicMock()
        mock_redis.client = MagicMock()
        mock_redis.client.hset = AsyncMock()

        mock_scheduler = MagicMock()
        mock_scheduler.trigger_now = AsyncMock(side_effect=Exception("Connection failed"))

        request = TriggerRequest(source_id="source-1")

        with patch("api.endpoints.pipeline.uuid.uuid4", return_value=uuid.UUID("12345678-1234-5678-1234-567812345678")):
            with pytest.raises(HTTPException) as exc_info:
                await trigger_pipeline(
                    request=request,
                    _="test-key",
                    redis=mock_redis,
                    scheduler=mock_scheduler,
                )
            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_task_status_found(self):
        """Test GET /pipeline/tasks/{task_id} returns status."""
        from api.endpoints.pipeline import get_task_status

        mock_redis = MagicMock()
        mock_redis.client = MagicMock()
        mock_redis.client.hget = AsyncMock(return_value=json.dumps({
            "task_id": "task-123",
            "status": "completed",
            "source_id": "source-1",
            "queued_at": "2024-01-01T00:00:00",
        }))

        result = await get_task_status(
            task_id="task-123",
            _="test-key",
            redis=mock_redis,
        )
        assert result.task_id == "task-123"
        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_get_task_status_not_found(self):
        """Test GET /pipeline/tasks/{task_id} returns 404."""
        from api.endpoints.pipeline import get_task_status

        mock_redis = MagicMock()
        mock_redis.client = MagicMock()
        mock_redis.client.hget = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_task_status(
                task_id="missing-task",
                _="test-key",
                redis=mock_redis,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_queue_stats(self):
        """Test GET /pipeline/queue/stats endpoint."""
        from api.endpoints.pipeline import get_queue_stats

        mock_redis = MagicMock()
        mock_redis.client = MagicMock()
        mock_redis.client.llen = AsyncMock(return_value=5)
        mock_redis.client.hgetall = AsyncMock(return_value={
            "task-1": json.dumps({"status": "completed"}),
            "task-2": json.dumps({"status": "running"}),
        })

        result = await get_queue_stats(
            _="test-key",
            redis=mock_redis,
        )
        assert result["queue_depth"] == 5
        assert result["total_tasks"] == 2

    def test_get_redis_client_not_initialized(self):
        """Test get_redis_client raises 503 when not initialized."""
        from api.endpoints.pipeline import get_redis_client

        with patch("api.endpoints.pipeline._redis_client", None):
            with pytest.raises(HTTPException) as exc_info:
                get_redis_client()
            assert exc_info.value.status_code == 503

    def test_get_source_scheduler_not_initialized(self):
        """Test get_source_scheduler raises 503 when not initialized."""
        from api.endpoints.pipeline import get_source_scheduler

        with patch("api.endpoints.pipeline._source_scheduler", None):
            with pytest.raises(HTTPException) as exc_info:
                get_source_scheduler()
            assert exc_info.value.status_code == 503


class TestArticlesEndpoint:
    """Tests for articles endpoints."""

    def test_article_list_response_model(self):
        """Test ArticleListResponse model."""
        from api.endpoints.articles import ArticleListResponse

        response = ArticleListResponse(
            items=[],
            total=0,
            page=1,
            page_size=20,
            total_pages=0,
        )
        assert response.total == 0
        assert response.page == 1

    def test_article_list_response_with_items(self):
        """Test ArticleListResponse with items."""
        from api.endpoints.articles import ArticleListResponse

        response = ArticleListResponse(
            items=[{"id": "1", "title": "Test"}],
            total=1,
            page=1,
            page_size=20,
            total_pages=1,
        )
        assert len(response.items) == 1
        assert response.total == 1

    def test_article_detail_response_model(self):
        """Test ArticleDetailResponse model."""
        from api.endpoints.articles import ArticleDetailResponse

        response = ArticleDetailResponse(
            id="123e4567-e89b-12d3-a456-426614174000",
            source_url="https://example.com/article",
            source_host="example.com",
            is_news=True,
            title="Test Title",
            body="Test body",
            category=None,
            language="zh",
            region=None,
            summary=None,
            event_time=None,
            subjects=None,
            key_data=None,
            impact=None,
            score=0.8,
            sentiment="neutral",
            sentiment_score=0.5,
            primary_emotion=None,
            credibility_score=0.9,
            source_credibility=0.85,
            cross_verification=0.7,
            content_check_score=0.95,
            publish_time=None,
            created_at="2024-01-01T00:00:00+00:00",
            updated_at="2024-01-01T00:00:00+00:00",
        )
        assert response.title == "Test Title"
        assert response.score == 0.8

    def test_article_to_dict(self):
        """Test _article_to_dict conversion function."""
        from api.endpoints.articles import _article_to_dict
        from core.db.models import Article, CategoryType, EmotionType

        article = MagicMock(spec=Article)
        article.id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        article.source_url = "https://example.com/article"
        article.source_host = "example.com"
        article.is_news = True
        article.title = "Test Title"
        article.body = "Test body"
        article.category = CategoryType.TECHNOLOGY
        article.language = "zh"
        article.region = "CN"
        article.summary = "Summary"
        article.event_time = None
        article.subjects = ["subject1"]
        article.key_data = ["data1"]
        article.impact = "high"
        article.score = 0.85
        article.sentiment = "positive"
        article.sentiment_score = 0.75
        article.primary_emotion = EmotionType.OPTIMISTIC
        article.credibility_score = 0.9
        article.source_credibility = 0.8
        article.cross_verification = 0.7
        article.content_check_score = 0.95
        article.publish_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        article.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        article.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        result = _article_to_dict(article)
        assert result["title"] == "Test Title"
        assert result["category"] == "科技"
        assert result["score"] == 0.85

    @pytest.mark.asyncio
    async def test_list_articles_endpoint(self):
        """Test GET /articles endpoint with filters."""
        from api.endpoints.articles import list_articles

        mock_article = MagicMock()
        mock_article.id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        mock_article.source_url = "https://example.com/article"
        mock_article.source_host = "example.com"
        mock_article.is_news = True
        mock_article.title = "Test Article"
        mock_article.body = "Body"
        mock_article.category = None
        mock_article.language = "zh"
        mock_article.region = None
        mock_article.summary = None
        mock_article.event_time = None
        mock_article.subjects = None
        mock_article.key_data = None
        mock_article.impact = None
        mock_article.score = 0.8
        mock_article.sentiment = None
        mock_article.sentiment_score = None
        mock_article.primary_emotion = None
        mock_article.credibility_score = None
        mock_article.source_credibility = None
        mock_article.cross_verification = None
        mock_article.content_check_score = None
        mock_article.publish_time = None
        mock_article.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mock_article.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        mock_articles_result = MagicMock()
        mock_articles_result.scalars.return_value.all.return_value = [mock_article]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[mock_count_result, mock_articles_result])

        mock_pool = MagicMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await list_articles(
            page=1,
            page_size=20,
            category=None,
            source_host=None,
            min_score=None,
            min_credibility=None,
            sort_by="publish_time",
            sort_order="desc",
            _="test-key",
            pool=mock_pool,
        )
        assert result.total == 1

    @pytest.mark.asyncio
    async def test_get_article_endpoint_found(self):
        """Test GET /articles/{article_id} returns article."""
        from api.endpoints.articles import get_article

        mock_article = MagicMock()
        mock_article.id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        mock_article.source_url = "https://example.com/article"
        mock_article.source_host = "example.com"
        mock_article.is_news = True
        mock_article.title = "Test Article"
        mock_article.body = "Body"
        mock_article.category = None
        mock_article.language = "zh"
        mock_article.region = None
        mock_article.summary = None
        mock_article.event_time = None
        mock_article.subjects = None
        mock_article.key_data = None
        mock_article.impact = None
        mock_article.score = 0.8
        mock_article.sentiment = None
        mock_article.sentiment_score = None
        mock_article.primary_emotion = None
        mock_article.credibility_score = None
        mock_article.source_credibility = None
        mock_article.cross_verification = None
        mock_article.content_check_score = None
        mock_article.publish_time = None
        mock_article.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mock_article.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_article

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool = MagicMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await get_article(
            article_id="12345678-1234-5678-1234-567812345678",
            _="test-key",
            pool=mock_pool,
        )
        assert result.title == "Test Article"

    @pytest.mark.asyncio
    async def test_get_article_endpoint_invalid_uuid(self):
        """Test GET /articles/{article_id} returns 400 for invalid UUID."""
        from api.endpoints.articles import get_article

        mock_pool = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_article(
                article_id="invalid-uuid",
                _="test-key",
                pool=mock_pool,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_get_article_endpoint_not_found(self):
        """Test GET /articles/{article_id} returns 404 for missing article."""
        from api.endpoints.articles import get_article

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool = MagicMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_article(
                article_id="12345678-1234-5678-1234-567812345678",
                _="test-key",
                pool=mock_pool,
            )
        assert exc_info.value.status_code == 404

    def test_get_postgres_pool_not_initialized(self):
        """Test get_postgres_pool raises 503 when not initialized."""
        from api.endpoints.articles import get_postgres_pool

        with patch("api.endpoints.articles._postgres_pool", None):
            with pytest.raises(HTTPException) as exc_info:
                get_postgres_pool()
            assert exc_info.value.status_code == 503


class TestGraphEndpoint:
    """Tests for graph endpoints."""

    def test_entity_response_model(self):
        """Test EntityResponse model."""
        from api.endpoints.graph import EntityResponse

        response = EntityResponse(
            id="123",
            canonical_name="Test Entity",
            type="person",
            aliases=["alias1", "alias2"],
            description="A test entity",
            updated_at="2024-01-01T00:00:00",
        )
        assert response.canonical_name == "Test Entity"
        assert response.type == "person"

    def test_entity_relationship_model(self):
        """Test EntityRelationship model."""
        from api.endpoints.graph import EntityRelationship

        rel = EntityRelationship(
            target="Target Entity",
            relation_type="RELATED_TO",
            source_article_id="article-123",
            created_at="2024-01-01T00:00:00",
        )
        assert rel.target == "Target Entity"
        assert rel.relation_type == "RELATED_TO"

    def test_entity_with_relations_model(self):
        """Test EntityWithRelations model."""
        from api.endpoints.graph import EntityWithRelations, EntityResponse

        entity = EntityResponse(
            id="123",
            canonical_name="Test Entity",
            type="person",
            aliases=None,
            description=None,
            updated_at=None,
        )
        response = EntityWithRelations(
            entity=entity,
            relationships=[],
            related_entities=[],
            mentioned_in_articles=[],
        )
        assert response.entity.canonical_name == "Test Entity"

    def test_article_graph_response_model(self):
        """Test ArticleGraphResponse model."""
        from api.endpoints.graph import (
            ArticleGraphResponse,
            ArticleGraphNode,
            EntityResponse,
            ArticleGraphRelationship,
        )

        response = ArticleGraphResponse(
            article=ArticleGraphNode(
                id="123",
                title="Test Article",
                category="科技",
                publish_time="2024-01-01T00:00:00",
                score=0.8,
            ),
            entities=[],
            relationships=[],
            related_articles=[],
        )
        assert response.article.title == "Test Article"

    def test_article_graph_node_model(self):
        """Test ArticleGraphNode model."""
        from api.endpoints.graph import ArticleGraphNode

        node = ArticleGraphNode(
            id="article-123",
            title="Test Article",
            category="tech",
            publish_time="2024-01-01T00:00:00",
            score=0.85,
        )
        assert node.id == "article-123"
        assert node.score == 0.85

    def test_article_graph_relationship_model(self):
        """Test ArticleGraphRelationship model."""
        from api.endpoints.graph import ArticleGraphRelationship

        rel = ArticleGraphRelationship(
            source_id="entity-1",
            target_id="entity-2",
            relation_type="RELATED_TO",
            properties={"weight": 0.9},
        )
        assert rel.source_id == "entity-1"
        assert rel.properties["weight"] == 0.9

    @pytest.mark.asyncio
    async def test_get_entity_endpoint_found(self):
        """Test GET /graph/entities/{name} returns entity."""
        from api.endpoints.graph import get_entity

        class AsyncIterator:
            def __init__(self, items):
                self.items = items
                self.index = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.index >= len(self.items):
                    raise StopAsyncIteration
                item = self.items[self.index]
                self.index += 1
                return item

        mock_session = AsyncMock()

        entity_result = AsyncMock()
        entity_result.single = AsyncMock(return_value={
            "id": "entity-123",
            "canonical_name": "Test Entity",
            "type": "person",
            "aliases": ["alias1"],
            "description": "Test description",
            "updated_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        })

        empty_result = AsyncMock()
        empty_result.__aiter__ = lambda self: AsyncIterator([]).__aiter__()
        empty_result.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

        mock_session.run = AsyncMock(side_effect=[
            entity_result,
            empty_result,
            empty_result,
            empty_result,
        ])

        mock_neo4j = MagicMock()
        mock_neo4j.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_neo4j.session.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("api.endpoints.graph.get_neo4j_client", return_value=mock_neo4j):
            result = await get_entity(
                name="Test%20Entity",
                limit=10,
                _="test-key",
                neo4j=mock_neo4j,
            )
        assert result.entity.canonical_name == "Test Entity"

    @pytest.mark.asyncio
    async def test_get_entity_endpoint_not_found(self):
        """Test GET /graph/entities/{name} returns 404."""
        from api.endpoints.graph import get_entity

        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        mock_neo4j = MagicMock()
        mock_neo4j.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_neo4j.session.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("api.endpoints.graph.get_neo4j_client", return_value=mock_neo4j):
            with pytest.raises(HTTPException) as exc_info:
                await get_entity(
                    name="Missing%20Entity",
                    limit=10,
                    _="test-key",
                    neo4j=mock_neo4j,
                )
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_article_graph_endpoint_found(self):
        """Test GET /graph/articles/{article_id}/graph returns graph."""
        from api.endpoints.graph import get_article_graph

        class AsyncIterator:
            def __init__(self, items):
                self.items = items
                self.index = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.index >= len(self.items):
                    raise StopAsyncIteration
                item = self.items[self.index]
                self.index += 1
                return item

        mock_session = AsyncMock()

        mock_article_result = AsyncMock()
        mock_article_result.single = AsyncMock(return_value={
            "id": "article-123",
            "title": "Test Article",
            "category": "tech",
            "publish_time": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "score": 0.85,
        })

        empty_result = AsyncMock()
        empty_result.__aiter__ = lambda self: AsyncIterator([]).__aiter__()
        empty_result.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

        mock_session.run = AsyncMock(side_effect=[
            mock_article_result,
            empty_result,
            empty_result,
            empty_result,
        ])

        mock_neo4j = MagicMock()
        mock_neo4j.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_neo4j.session.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("api.endpoints.graph.get_neo4j_client", return_value=mock_neo4j):
            result = await get_article_graph(
                article_id="article-123",
                _="test-key",
                neo4j=mock_neo4j,
            )
        assert result.article.title == "Test Article"

    @pytest.mark.asyncio
    async def test_get_article_graph_endpoint_not_found(self):
        """Test GET /graph/articles/{article_id}/graph returns 404."""
        from api.endpoints.graph import get_article_graph

        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        mock_neo4j = MagicMock()
        mock_neo4j.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_neo4j.session.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("api.endpoints.graph.get_neo4j_client", return_value=mock_neo4j):
            with pytest.raises(HTTPException) as exc_info:
                await get_article_graph(
                    article_id="missing-article",
                    _="test-key",
                    neo4j=mock_neo4j,
                )
            assert exc_info.value.status_code == 404

    def test_get_neo4j_client_not_initialized(self):
        """Test get_neo4j_client raises 503 when not initialized."""
        from api.endpoints.graph import get_neo4j_client

        with patch("api.endpoints.graph._neo4j_client", None):
            with pytest.raises(HTTPException) as exc_info:
                get_neo4j_client()
            assert exc_info.value.status_code == 503


class TestAdminEndpoint:
    """Tests for admin endpoints."""

    def test_authority_response_model(self):
        """Test AuthorityResponse model."""
        from api.endpoints.admin import AuthorityResponse

        response = AuthorityResponse(
            id=1,
            host="example.com",
            authority=0.85,
            tier=1,
            description="High authority source",
            needs_review=False,
            auto_score=0.80,
            updated_at="2024-01-01T00:00:00",
        )
        assert response.host == "example.com"
        assert response.authority == 0.85

    def test_update_authority_request_model(self):
        """Test UpdateAuthorityRequest model."""
        from api.endpoints.admin import UpdateAuthorityRequest

        request = UpdateAuthorityRequest(
            authority=0.9,
            tier=1,
        )
        assert request.authority == 0.9
        assert request.tier == 1

    def test_update_authority_request_validation(self):
        """Test UpdateAuthorityRequest field validation."""
        from api.endpoints.admin import UpdateAuthorityRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            UpdateAuthorityRequest(authority=1.5)

        with pytest.raises(ValidationError):
            UpdateAuthorityRequest(tier=6)

    def test_update_authority_response_model(self):
        """Test UpdateAuthorityResponse model."""
        from api.endpoints.admin import UpdateAuthorityResponse

        response = UpdateAuthorityResponse(
            host="example.com",
            authority=0.9,
            tier=1,
            description="Updated",
        )
        assert response.host == "example.com"
        assert response.authority == 0.9

    @pytest.mark.asyncio
    async def test_list_authorities_endpoint(self):
        """Test GET /admin/sources/authorities endpoint."""
        from api.endpoints.admin import list_authorities

        mock_authority = MagicMock()
        mock_authority.id = 1
        mock_authority.host = "example.com"
        mock_authority.authority = 0.85
        mock_authority.tier = 1
        mock_authority.description = "Test"
        mock_authority.needs_review = False
        mock_authority.auto_score = 0.80
        mock_authority.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_repo = MagicMock()
        mock_repo.get_needs_review = AsyncMock(return_value=[mock_authority])

        result = await list_authorities(
            needs_review_only=True,
            _="test-key",
            repo=mock_repo,
        )
        assert len(result) == 1
        assert result[0].host == "example.com"

    @pytest.mark.asyncio
    async def test_update_authority_endpoint_success(self):
        """Test PATCH /admin/sources/{host}/authority endpoint."""
        from api.endpoints.admin import update_authority, UpdateAuthorityRequest

        mock_authority = MagicMock()
        mock_authority.authority = 0.7
        mock_authority.tier = 2

        mock_repo = MagicMock()
        mock_repo.get_or_create = AsyncMock(return_value=mock_authority)
        mock_repo.update_authority = AsyncMock()

        request = UpdateAuthorityRequest(authority=0.9, tier=1)

        result = await update_authority(
            host="example.com",
            request=request,
            _="test-key",
            repo=mock_repo,
        )
        assert result.host == "example.com"
        mock_repo.update_authority.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_authority_endpoint_no_fields(self):
        """Test PATCH /admin/sources/{host}/authority returns 400 when no fields."""
        from api.endpoints.admin import update_authority, UpdateAuthorityRequest

        mock_repo = MagicMock()

        request = UpdateAuthorityRequest()

        with pytest.raises(HTTPException) as exc_info:
            await update_authority(
                host="example.com",
                request=request,
                _="test-key",
                repo=mock_repo,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_get_authority_endpoint(self):
        """Test GET /admin/sources/{host}/authority endpoint."""
        from api.endpoints.admin import get_authority

        mock_authority = MagicMock()
        mock_authority.id = 1
        mock_authority.host = "example.com"
        mock_authority.authority = 0.85
        mock_authority.tier = 1
        mock_authority.description = "Test"
        mock_authority.needs_review = False
        mock_authority.auto_score = 0.80
        mock_authority.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_repo = MagicMock()
        mock_repo.get_or_create = AsyncMock(return_value=mock_authority)

        result = await get_authority(
            host="example.com",
            _="test-key",
            repo=mock_repo,
        )
        assert result.host == "example.com"
        assert result.authority == 0.85

    def test_get_source_authority_repo_not_initialized(self):
        """Test get_source_authority_repo raises 503 when not initialized."""
        from api.endpoints.admin import get_source_authority_repo

        with patch("api.endpoints.admin._source_authority_repo", None):
            with pytest.raises(HTTPException) as exc_info:
                get_source_authority_repo()
            assert exc_info.value.status_code == 503


class TestRouter:
    """Tests for API router."""

    def test_router_exists(self):
        """Test router is defined."""
        from api.router import api_router

        assert api_router is not None

    def test_router_has_prefix(self):
        """Test router has correct prefix."""
        from api.router import api_router

        assert api_router.prefix == "/api/v1"


class TestMetricsEndpoint:
    """Tests for metrics endpoint."""

    def test_metrics_collector_exists(self):
        """Test metrics collector is available."""
        from core.observability.metrics import MetricsCollector, metrics

        assert MetricsCollector is not None
        assert metrics is not None

    def test_metrics_has_counters(self):
        """Test metrics has expected counters."""
        from core.observability.metrics import metrics

        assert hasattr(metrics, 'llm_call_total')
        assert hasattr(metrics, 'fallback_total')
        assert hasattr(metrics, 'fetch_total')

    def test_metrics_has_gauges(self):
        """Test metrics has expected gauges."""
        from core.observability.metrics import metrics

        assert hasattr(metrics, 'pipeline_queue_depth')

    def test_metrics_has_histograms(self):
        """Test metrics has expected histograms."""
        from core.observability.metrics import metrics

        assert hasattr(metrics, 'llm_call_latency')
        assert hasattr(metrics, 'pipeline_stage_latency')
        assert hasattr(metrics, 'fetch_latency')
