# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Sources API endpoints - updated for new repo interface."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


class TestSourceResponseModel:
    """Tests for Source response models."""

    def test_source_response_model(self):
        """Test SourceResponse model."""
        from api.endpoints.content.sources import SourceResponse

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

    def test_source_response_with_credibility(self):
        """Test SourceResponse includes credibility and tier."""
        from api.endpoints.content.sources import SourceResponse

        response = SourceResponse(
            id="reuters",
            name="Reuters",
            url="https://reuters.com/feed.xml",
            source_type="rss",
            enabled=True,
            interval_minutes=30,
            per_host_concurrency=2,
            credibility=0.95,
            tier=1,
        )
        assert response.credibility == 0.95
        assert response.tier == 1

    def test_source_create_request_model(self):
        """Test SourceCreateRequest model validation."""
        from api.endpoints.content.sources import SourceCreateRequest

        request = SourceCreateRequest(
            id="new_source",
            name="New Source",
            url="https://example.com/new.xml",
        )
        assert request.id == "new_source"
        assert request.enabled is True
        assert request.credibility is None
        assert request.tier is None

    def test_source_create_request_with_credibility(self):
        """Test SourceCreateRequest with credibility and tier."""
        from api.endpoints.content.sources import SourceCreateRequest

        request = SourceCreateRequest(
            id="xinhua",
            name="Xinhua",
            url="https://xinhua.com/feed.xml",
            credibility=0.98,
            tier=1,
        )
        assert request.credibility == 0.98
        assert request.tier == 1

    def test_source_create_request_credibility_validation(self):
        """Test SourceCreateRequest rejects invalid credibility."""
        from api.endpoints.content.sources import SourceCreateRequest

        with pytest.raises(ValidationError):
            SourceCreateRequest(
                id="test",
                name="Test",
                url="https://example.com",
                credibility=1.5,  # Invalid: > 1.0
            )

    def test_source_create_request_tier_validation(self):
        """Test SourceCreateRequest rejects invalid tier."""
        from api.endpoints.content.sources import SourceCreateRequest

        with pytest.raises(ValidationError):
            SourceCreateRequest(
                id="test",
                name="Test",
                url="https://example.com",
                tier=4,  # Invalid: > 3
            )

    def test_source_update_request_model(self):
        """Test SourceUpdateRequest model validation."""
        from api.endpoints.content.sources import SourceUpdateRequest

        request = SourceUpdateRequest(
            name="Updated Name",
            enabled=False,
            interval_minutes=60,
            credibility=0.85,
            tier=2,
        )
        assert request.name == "Updated Name"
        assert request.enabled is False
        assert request.url is None
        assert request.credibility == 0.85
        assert request.tier == 2

    def test_source_response_from_config(self):
        """Test SourceResponse.from_config factory method."""
        from api.endpoints.content.sources import SourceResponse
        from modules.ingestion.domain.models import SourceConfig

        config = SourceConfig(
            id="test-id",
            name="Test",
            url="https://test.com/feed.xml",
            source_type="rss",
            enabled=True,
            interval_minutes=30,
            per_host_concurrency=2,
            credibility=0.90,
            tier=2,
        )
        response = SourceResponse.from_config(config)
        assert response.id == "test-id"
        assert response.name == "Test"
        assert response.credibility == 0.90
        assert response.tier == 2


class TestSourcesEndpoint:
    """Tests for sources endpoints with new repo interface."""

    @pytest.mark.asyncio
    async def test_list_sources_endpoint(self):
        """Test GET /sources endpoint."""
        from api.endpoints.content.sources import list_sources
        from modules.ingestion.domain.models import SourceConfig

        mock_repo = AsyncMock()
        mock_repo.list_sources = AsyncMock(
            return_value=[
                SourceConfig(
                    id="source-1",
                    name="Test Source",
                    url="https://test.com/feed.xml",
                    credibility=0.80,
                    tier=2,
                )
            ]
        )

        result = await list_sources(
            enabled_only=True,
            _="test-key",
            repo=mock_repo,
        )
        assert len(result.data) == 1
        assert result.data[0].id == "source-1"
        assert result.data[0].credibility == 0.80

    @pytest.mark.asyncio
    async def test_create_source_endpoint_success(self):
        """Test POST /sources endpoint creates new source."""
        from api.endpoints.content.sources import SourceCreateRequest, create_source
        from modules.ingestion.domain.models import SourceConfig

        new_config = SourceConfig(
            id="new-source",
            name="New Source",
            url="https://new.com/feed.xml",
            credibility=0.75,
            tier=2,
        )

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)
        mock_repo.upsert = AsyncMock(return_value=new_config)

        # Mock scheduler with registry
        mock_scheduler = MagicMock()
        mock_scheduler._registry = MagicMock()
        mock_scheduler._registry.add_source = MagicMock()

        # Mock fetcher returns valid RSS feed content
        valid_rss = (
            '<?xml version="1.0"?>'
            '<rss version="2.0"><channel>'
            "<title>Test Feed</title>"
            "<item><title>Entry 1</title><link>https://new.com/1</link></item>"
            "</channel></rss>"
        )
        mock_fetcher = AsyncMock()
        mock_fetcher.fetch = AsyncMock(return_value=(200, valid_rss, {}))

        request = SourceCreateRequest(
            id="new-source",
            name="New Source",
            url="https://new.com/feed.xml",
            credibility=0.75,
            tier=2,
        )

        result = await create_source(
            request=request,
            _="test-key",
            repo=mock_repo,
            scheduler=mock_scheduler,
            fetcher=mock_fetcher,
        )
        assert result.data.id == "new-source"
        mock_repo.upsert.assert_called_once()
        mock_scheduler._registry.add_source.assert_called_once_with(new_config)
        mock_fetcher.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_source_endpoint_conflict(self):
        """Test POST /sources returns 409 for existing source."""
        from api.endpoints.content.sources import SourceCreateRequest, create_source
        from modules.ingestion.domain.models import SourceConfig

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(
            return_value=SourceConfig(
                id="existing-source",
                name="Existing",
                url="https://existing.com/feed.xml",
            )
        )

        mock_fetcher = AsyncMock()

        request = SourceCreateRequest(
            id="existing-source",
            name="Existing",
            url="https://existing.com/feed.xml",
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_source(
                request=request,
                _="test-key",
                repo=mock_repo,
                fetcher=mock_fetcher,
            )
        assert exc_info.value.status_code == 409
        # Fetcher should not be called when source already exists
        mock_fetcher.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_source_endpoint_success(self):
        """Test PUT /sources/{source_id} endpoint."""
        from api.endpoints.content.sources import SourceUpdateRequest, update_source
        from modules.ingestion.domain.models import SourceConfig

        mock_existing = SourceConfig(
            id="source-1",
            name="Old Name",
            url="https://old.com/feed.xml",
            source_type="rss",
            enabled=True,
            interval_minutes=30,
            per_host_concurrency=2,
        )

        updated_config = SourceConfig(
            id="source-1",
            name="New Name",
            url="https://old.com/feed.xml",
            source_type="rss",
            enabled=False,
            interval_minutes=30,
            per_host_concurrency=2,
            credibility=0.85,
            tier=2,
        )

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=mock_existing)
        mock_repo.upsert = AsyncMock(return_value=updated_config)

        request = SourceUpdateRequest(name="New Name", enabled=False, credibility=0.85)

        result = await update_source(
            source_id="source-1",
            request=request,
            _="test-key",
            repo=mock_repo,
        )
        assert result.data.name == "New Name"
        mock_repo.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_source_endpoint_not_found(self):
        """Test PUT /sources/{source_id} returns 404 for missing source."""
        from api.endpoints.content.sources import SourceUpdateRequest, update_source

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)

        request = SourceUpdateRequest(name="New Name")

        with pytest.raises(HTTPException) as exc_info:
            await update_source(
                source_id="missing-source",
                request=request,
                _="test-key",
                repo=mock_repo,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_source_endpoint_success(self):
        """Test DELETE /sources/{source_id} endpoint."""
        from api.endpoints.content.sources import delete_source

        mock_repo = AsyncMock()
        mock_repo.delete = AsyncMock(return_value=True)

        await delete_source(
            source_id="source-1",
            _="test-key",
            repo=mock_repo,
        )
        mock_repo.delete.assert_called_once_with("source-1")

    @pytest.mark.asyncio
    async def test_delete_source_endpoint_not_found(self):
        """Test DELETE /sources/{source_id} returns 404 for missing source."""
        from api.endpoints.content.sources import delete_source

        mock_repo = AsyncMock()
        mock_repo.delete = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await delete_source(
                source_id="missing-source",
                _="test-key",
                repo=mock_repo,
            )
        assert exc_info.value.status_code == 404

    # NOTE: _source_config_repo module-level variable removed in favor of Endpoints class
    # The get_source_config_repo function now uses api.dependencies.get_source_config_repo()


# Valid RSS feed content for tests
_VALID_RSS = (
    '<?xml version="1.0"?>'
    '<rss version="2.0"><channel>'
    "<title>Test Feed</title>"
    "<item><title>Entry 1</title><link>https://example.com/1</link></item>"
    "<item><title>Entry 2</title><link>https://example.com/2</link></item>"
    "</channel></rss>"
)

_EMPTY_RSS = (
    '<?xml version="1.0"?>'
    '<rss version="2.0"><channel>'
    "<title>Empty Feed</title>"
    "</channel></rss>"
)

_MALFORMED_XML = "<rss><channel><title>Broken"


class TestFeedValidation:
    """Tests for _validate_feed_reachable function."""

    @pytest.mark.asyncio
    async def test_validate_feed_reachable_success(self):
        """Test feed validation passes for valid RSS with entries."""
        from api.endpoints.content.sources import _validate_feed_reachable

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch = AsyncMock(return_value=(200, _VALID_RSS, {}))

        # Should not raise
        await _validate_feed_reachable(
            url="https://example.com/feed.xml",
            fetcher=mock_fetcher,
        )

    @pytest.mark.asyncio
    async def test_validate_feed_reachable_unreachable_url(self):
        """Test feed validation fails when URL is not reachable."""
        from api.endpoints.content.sources import _validate_feed_reachable

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch = AsyncMock(side_effect=ConnectionError("DNS resolution failed"))

        with pytest.raises(HTTPException) as exc_info:
            await _validate_feed_reachable(
                url="https://nonexistent.example.com/feed.xml",
                fetcher=mock_fetcher,
            )
        assert exc_info.value.status_code == 422
        assert "not reachable" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_validate_feed_reachable_non_200_status(self):
        """Test feed validation fails for non-200 HTTP status."""
        from api.endpoints.content.sources import _validate_feed_reachable

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch = AsyncMock(return_value=(404, "Not Found", {}))

        with pytest.raises(HTTPException) as exc_info:
            await _validate_feed_reachable(
                url="https://example.com/missing.xml",
                fetcher=mock_fetcher,
            )
        assert exc_info.value.status_code == 422
        assert "404" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_validate_feed_reachable_empty_content(self):
        """Test feed validation fails for empty response content."""
        from api.endpoints.content.sources import _validate_feed_reachable

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch = AsyncMock(return_value=(200, "", {}))

        with pytest.raises(HTTPException) as exc_info:
            await _validate_feed_reachable(
                url="https://example.com/empty.xml",
                fetcher=mock_fetcher,
            )
        assert exc_info.value.status_code == 422
        assert "empty" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_validate_feed_reachable_no_entries(self):
        """Test feed validation fails for RSS with no entries."""
        from api.endpoints.content.sources import _validate_feed_reachable

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch = AsyncMock(return_value=(200, _EMPTY_RSS, {}))

        with pytest.raises(HTTPException) as exc_info:
            await _validate_feed_reachable(
                url="https://example.com/empty-feed.xml",
                fetcher=mock_fetcher,
            )
        assert exc_info.value.status_code == 422
        assert "no entries" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_validate_feed_reachable_malformed_xml(self):
        """Test feed validation fails for malformed XML."""
        from api.endpoints.content.sources import _validate_feed_reachable

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch = AsyncMock(return_value=(200, _MALFORMED_XML, {}))

        with pytest.raises(HTTPException) as exc_info:
            await _validate_feed_reachable(
                url="https://example.com/broken.xml",
                fetcher=mock_fetcher,
            )
        assert exc_info.value.status_code == 422
        assert "valid RSS/Atom" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_validate_feed_reachable_timeout(self):
        """Test feed validation fails on timeout."""
        from api.endpoints.content.sources import _validate_feed_reachable

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch = AsyncMock(side_effect=TimeoutError())

        with pytest.raises(HTTPException) as exc_info:
            await _validate_feed_reachable(
                url="https://slow.example.com/feed.xml",
                fetcher=mock_fetcher,
            )
        assert exc_info.value.status_code == 422
        assert "timed out" in exc_info.value.detail.lower()


class TestCreateSourceWithValidation:
    """Tests for create_source endpoint with feed validation integration."""

    @pytest.mark.asyncio
    async def test_create_source_rejects_unreachable_feed(self):
        """Test POST /sources returns 422 for unreachable feed URL."""
        from api.endpoints.content.sources import SourceCreateRequest, create_source

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch = AsyncMock(side_effect=ConnectionError("Connection refused"))

        request = SourceCreateRequest(
            id="bad-source",
            name="Bad Source",
            url="https://unreachable.example.com/feed.xml",
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_source(
                request=request,
                _="test-key",
                repo=mock_repo,
                scheduler=MagicMock(),
                fetcher=mock_fetcher,
            )
        assert exc_info.value.status_code == 422
        # Source should not be persisted
        mock_repo.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_source_rejects_feed_with_no_entries(self):
        """Test POST /sources returns 422 for feed with no entries."""
        from api.endpoints.content.sources import SourceCreateRequest, create_source

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch = AsyncMock(return_value=(200, _EMPTY_RSS, {}))

        request = SourceCreateRequest(
            id="empty-feed",
            name="Empty Feed",
            url="https://example.com/empty.xml",
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_source(
                request=request,
                _="test-key",
                repo=mock_repo,
                scheduler=MagicMock(),
                fetcher=mock_fetcher,
            )
        assert exc_info.value.status_code == 422
        mock_repo.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_source_rejects_non_200_feed(self):
        """Test POST /sources returns 422 for feed returning HTTP 404."""
        from api.endpoints.content.sources import SourceCreateRequest, create_source

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch = AsyncMock(return_value=(404, "Not Found", {}))

        request = SourceCreateRequest(
            id="missing-feed",
            name="Missing Feed",
            url="https://example.com/missing.xml",
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_source(
                request=request,
                _="test-key",
                repo=mock_repo,
                scheduler=MagicMock(),
                fetcher=mock_fetcher,
            )
        assert exc_info.value.status_code == 422
        mock_repo.upsert.assert_not_called()
