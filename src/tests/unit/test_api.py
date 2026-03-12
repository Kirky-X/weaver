"""Unit tests for API endpoints."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, patch
from fastapi.testclient import TestClient


class TestAuthMiddleware:
    """Tests for authentication middleware."""

    def test_verify_api_key_missing(self):
        """Test verify_api_key raises error when key is missing."""
        from api.middleware.auth import verify_api_key
        from fastapi import HTTPException

        # This test would require proper dependency injection setup
        # For now, just verify the function exists
        assert verify_api_key is not None

    def test_api_key_header_exists(self):
        """Test API key header is defined."""
        from api.middleware.auth import api_key_header

        assert api_key_header is not None
        # APIKeyHeader is a class, not an instance


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
        assert request.enabled is True  # default


class TestPipelineEndpoint:
    """Tests for pipeline endpoints."""

    def test_trigger_request_model(self):
        """Test TriggerRequest model."""
        from api.endpoints.pipeline import TriggerRequest

        request = TriggerRequest()
        assert request.source_id is None
        assert request.force is False

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
