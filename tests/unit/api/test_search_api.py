# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for search API endpoints."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


class TestSearchModels:
    """Tests for search request/response models."""

    def test_search_response_model(self) -> None:
        """Test SearchResponse model."""
        from api.endpoints.search import SearchResponse

        response = SearchResponse(
            query="test query",
            answer="This is the answer",
            context_tokens=1000,
            confidence=0.95,
            search_type="local",
            entities=["Apple", "Microsoft"],
            sources=[{"article_id": "123", "similarity": 0.9}],
            metadata={"total_results": 1},
        )
        assert response.query == "test query"
        assert response.answer == "This is the answer"
        assert response.context_tokens == 1000
        assert response.confidence == 0.95
        assert response.search_type == "local"
        assert len(response.entities) == 2
        assert len(response.sources) == 1

    def test_drift_search_request_model(self) -> None:
        """Test DriftSearchRequest model."""
        from api.endpoints.search import DriftSearchRequest

        request = DriftSearchRequest(
            query="test query",
            primer_k=5,
            max_follow_ups=3,
            confidence_threshold=0.8,
        )
        assert request.query == "test query"
        assert request.primer_k == 5
        assert request.max_follow_ups == 3
        assert request.confidence_threshold == 0.8

    def test_drift_search_response_model(self) -> None:
        """Test DriftSearchResponse model."""
        from api.endpoints.search import DriftSearchResponse

        response = DriftSearchResponse(
            query="test query",
            answer="DRIFT answer",
            confidence=0.85,
            search_type="drift",
            hierarchy={"primer": {}, "follow_ups": []},
            primer_communities=3,
            follow_up_iterations=2,
            total_llm_calls=5,
            drift_mode="auto",
            metadata={"total_time_ms": 1500},
        )
        assert response.query == "test query"
        assert response.search_type == "drift"
        assert response.primer_communities == 3

    def test_causal_search_request_model(self) -> None:
        """Test CausalSearchRequest model."""
        from api.endpoints.search import CausalSearchRequest

        request = CausalSearchRequest(
            query="cause and effect",
            max_depth=3,
            min_confidence=0.8,
        )
        assert request.query == "cause and effect"
        assert request.max_depth == 3
        assert request.min_confidence == 0.8

    def test_causal_search_response_model(self) -> None:
        """Test CausalSearchResponse model."""
        from api.endpoints.search import CausalSearchResponse

        response = CausalSearchResponse(
            query="why did X happen?",
            answer="X happened because of Y",
            causal_chain=[{"id": "1", "content": "cause", "score": 0.9}],
            confidence=0.85,
            metadata={"depth": 3},
        )
        assert response.query == "why did X happen?"
        assert len(response.causal_chain) == 1

    def test_temporal_search_request_model(self) -> None:
        """Test TemporalSearchRequest model."""
        from api.endpoints.search import TemporalSearchRequest

        request = TemporalSearchRequest(
            query="recent events",
            time_window_days=7,
            limit=20,
        )
        assert request.query == "recent events"
        assert request.time_window_days == 7
        assert request.limit == 20

    def test_temporal_search_response_model(self) -> None:
        """Test TemporalSearchResponse model."""
        from api.endpoints.search import TemporalSearchResponse

        response = TemporalSearchResponse(
            query="when did X happen?",
            events=[{"id": "1", "timestamp": "2024-01-01"}],
            time_range={"start": "2024-01-01", "end": "2024-01-07", "window_days": 7},
            metadata={"limit": 10},
        )
        assert response.query == "when did X happen?"
        assert len(response.events) == 1
        assert response.time_range["window_days"] == 7


class TestSearchRouter:
    """Tests for search router configuration."""

    def test_router_prefix(self) -> None:
        """Test router has correct prefix."""
        from api.endpoints.search import router

        assert router.prefix == "/search"

    def test_router_tags(self) -> None:
        """Test router has correct tags."""
        from api.endpoints.search import router

        assert "search" in router.tags


class TestSearchEndpoints:
    """Tests for search endpoint functions."""

    @pytest.mark.asyncio
    async def test_result_to_response(self) -> None:
        """Test SearchResult to SearchResponse conversion."""
        from api.endpoints.search import SearchResponse, _result_to_response

        # Create mock SearchResult
        mock_result = MagicMock()
        mock_result.query = "test query"
        mock_result.answer = "test answer"
        mock_result.context_tokens = 100
        mock_result.confidence = 0.9
        mock_result.entities = ["Apple", "Microsoft"]
        mock_result.sources = [{"article_id": "123"}]
        mock_result.metadata = {"total": 1}

        response = _result_to_response(mock_result, "local")

        assert response.query == "test query"
        assert response.search_type == "local"
        assert isinstance(response, SearchResponse)


class TestSearchEngineDependency:
    """Tests for search engine dependency injection."""

    def test_local_search_engine_interface(self) -> None:
        """Test local search engine dependency exists."""
        from api.dependencies import get_local_search_engine

        assert callable(get_local_search_engine)

    def test_global_search_engine_interface(self) -> None:
        """Test global search engine dependency exists."""
        from api.dependencies import get_global_search_engine

        assert callable(get_global_search_engine)

    def test_hybrid_search_engine_interface(self) -> None:
        """Test hybrid search engine dependency exists."""
        from api.dependencies import get_hybrid_search_engine

        assert callable(get_hybrid_search_engine)
