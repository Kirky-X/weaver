# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for search API endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


class TestSearchRouter:
    """Tests for search router configuration."""

    def test_router_prefix(self) -> None:
        """Test router has correct prefix."""
        from api.endpoints.content.search import router

        assert router.prefix == "/search"

    def test_router_tags(self) -> None:
        """Test router has correct tags."""
        from api.endpoints.content.search import router

        assert "search" in router.tags


class TestSearchEndpoints:
    """Tests for search endpoint functions."""

    @pytest.mark.asyncio
    async def test_search_response_creation(self) -> None:
        """Test SearchResponse creation."""
        from api.endpoints.content.search import SearchResponse

        response = SearchResponse(
            query="test query",
            answer="test answer",
            context_tokens=100,
            confidence=0.9,
            search_type="local",
            entities=["Apple", "Microsoft"],
            sources=[{"article_id": "123"}],
            metadata={"total": 1},
        )

        assert response.query == "test query"
        assert response.search_type == "local"
        assert isinstance(response, SearchResponse)


class TestSearchEngineDependency:
    """Tests for search engine dependency injection."""

    def test_get_local_search_engine_returns_correct_type(self) -> None:
        """Test get_local_search_engine returns a LocalSearchEngine instance.

        Mocks the container (populated at startup) and verifies the dependency
        function returns the correct engine instance type.
        """
        import container as container_module
        from api.dependencies import get_local_search_engine
        from modules.knowledge.search import LocalSearchEngine

        # Create a real LocalSearchEngine with mocked ContextBuilder
        mock_context_builder = MagicMock()
        engine = LocalSearchEngine(context_builder=mock_context_builder)

        # Simulate container registration
        mock_container = MagicMock()
        mock_container.local_search_engine.return_value = engine
        original = container_module._container
        container_module._container = mock_container
        try:
            result = get_local_search_engine(container=mock_container)

            assert isinstance(result, LocalSearchEngine)
            assert result is engine
        finally:
            container_module._container = original

    def test_get_local_search_engine_raises_when_not_initialized(self) -> None:
        """Test get_local_search_engine raises HTTPException when not initialized."""
        import container as container_module
        from api.dependencies import get_local_search_engine

        mock_container = MagicMock()
        mock_container.local_search_engine.return_value = None
        original = container_module._container
        container_module._container = mock_container
        try:
            with pytest.raises(HTTPException) as exc_info:
                get_local_search_engine(container=mock_container)

            assert exc_info.value.status_code == 503
        finally:
            container_module._container = original
