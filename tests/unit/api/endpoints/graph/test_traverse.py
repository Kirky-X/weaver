# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for graph traverse endpoint."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers import assert_api_response

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def mock_graph_repo():
    """Create mock GraphRepository for testing."""
    repo = MagicMock()
    repo.traverse = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def auth_headers():
    """Create authentication headers."""
    return {"X-API-Key": "test-api-key"}


@pytest.fixture
def client(mock_graph_repo):
    """Create TestClient for graph traverse endpoints."""
    from api.dependencies import get_graph_repo
    from api.endpoints.graph.graph import router
    from api.middleware.auth import verify_api_key

    app = FastAPI()
    app.dependency_overrides[get_graph_repo] = lambda: mock_graph_repo
    app.dependency_overrides[verify_api_key] = lambda: "test-api-key"
    app.include_router(router)

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


# ── Test Data ─────────────────────────────────────────────────────

SAMPLE_TRAVERSE_RESULT = [
    {
        "nodes": [
            {"id": "e1", "canonical_name": "EntityA", "type": "PERSON", "description": "Test A"},
            {"id": "e2", "canonical_name": "EntityB", "type": "ORG", "description": "Test B"},
        ],
        "edges": [
            {"source": "EntityA", "target": "EntityB", "relation_type": "WORKS_AT", "weight": 1.0},
        ],
        "paths": [
            {
                "nodes": ["EntityA", "EntityB"],
                "edges": [{"source": "EntityA", "target": "EntityB", "relation_type": "WORKS_AT"}],
            }
        ],
    }
]


# ── Tests ─────────────────────────────────────────────────────────


class TestTraverseBasic:
    """Test basic traversal endpoint."""

    def test_traverse_basic(self, client, auth_headers, mock_graph_repo):
        """Test basic traversal from a starting entity."""
        mock_graph_repo.traverse = AsyncMock(return_value=SAMPLE_TRAVERSE_RESULT)

        request_data = {
            "start_entity": "EntityA",
            "max_depth": 3,
        }
        response = client.post("/graph/traverse", json=request_data, headers=auth_headers)

        data = assert_api_response(response)
        assert data["data"]["results"] is not None
        mock_graph_repo.traverse.assert_called_once()

    def test_traverse_with_relation_filter(self, client, auth_headers, mock_graph_repo):
        """Test traversal with relation type filtering."""
        mock_graph_repo.traverse = AsyncMock(return_value=SAMPLE_TRAVERSE_RESULT)

        request_data = {
            "start_entity": "EntityA",
            "max_depth": 3,
            "relation_types": ["WORKS_AT", "KNOWS"],
        }
        response = client.post("/graph/traverse", json=request_data, headers=auth_headers)

        data = assert_api_response(response)
        call_kwargs = mock_graph_repo.traverse.call_args[1]
        assert call_kwargs["relation_types"] == ["WORKS_AT", "KNOWS"]

    def test_traverse_max_depth_6_limit(self, client, auth_headers, mock_graph_repo):
        """Test that max depth is capped at 6."""
        request_data = {
            "start_entity": "EntityA",
            "max_depth": 10,  # Exceeds limit of 6
        }
        response = client.post("/graph/traverse", json=request_data, headers=auth_headers)

        # Should be rejected by validation (422)
        assert response.status_code == 422

    def test_traverse_max_results_1000_limit(self, client, auth_headers, mock_graph_repo):
        """Test that max_results is capped at 1000."""
        request_data = {
            "start_entity": "EntityA",
            "max_depth": 3,
            "max_results": 5000,  # Exceeds limit of 1000
        }
        response = client.post("/graph/traverse", json=request_data, headers=auth_headers)

        # Should be rejected by validation (422)
        assert response.status_code == 422

    def test_traverse_timeout(self, client, auth_headers, mock_graph_repo):
        """Test that timeout parameter is passed through."""
        mock_graph_repo.traverse = AsyncMock(return_value=SAMPLE_TRAVERSE_RESULT)

        request_data = {
            "start_entity": "EntityA",
            "max_depth": 3,
            "timeout_seconds": 5,
        }
        response = client.post("/graph/traverse", json=request_data, headers=auth_headers)

        data = assert_api_response(response)
        call_kwargs = mock_graph_repo.traverse.call_args[1]
        assert call_kwargs["timeout_seconds"] == 5

    def test_traverse_return_paths(self, client, auth_headers, mock_graph_repo):
        """Test traversal with return_paths enabled."""
        mock_graph_repo.traverse = AsyncMock(return_value=SAMPLE_TRAVERSE_RESULT)

        request_data = {
            "start_entity": "EntityA",
            "max_depth": 3,
            "return_paths": True,
        }
        response = client.post("/graph/traverse", json=request_data, headers=auth_headers)

        data = assert_api_response(response)
        call_kwargs = mock_graph_repo.traverse.call_args[1]
        assert call_kwargs["return_paths"] is True

    def test_traverse_aggregate_mode(self, client, auth_headers, mock_graph_repo):
        """Test traversal in aggregate mode."""
        aggregate_result = [
            {
                "nodes": [
                    {
                        "id": "e1",
                        "canonical_name": "EntityA",
                        "type": "PERSON",
                        "description": "Test A",
                    },
                ],
                "edges": [],
                "aggregate": {
                    "total_nodes": 5,
                    "total_edges": 3,
                    "relation_type_counts": {"WORKS_AT": 2, "KNOWS": 1},
                },
            }
        ]
        mock_graph_repo.traverse = AsyncMock(return_value=aggregate_result)

        request_data = {
            "start_entity": "EntityA",
            "max_depth": 3,
            "mode": "aggregate",
        }
        response = client.post("/graph/traverse", json=request_data, headers=auth_headers)

        data = assert_api_response(response)
        call_kwargs = mock_graph_repo.traverse.call_args[1]
        assert call_kwargs["mode"] == "aggregate"

    def test_traverse_min_confidence_filter(self, client, auth_headers, mock_graph_repo):
        """Test traversal with minimum confidence filtering."""
        mock_graph_repo.traverse = AsyncMock(return_value=SAMPLE_TRAVERSE_RESULT)

        request_data = {
            "start_entity": "EntityA",
            "max_depth": 3,
            "min_confidence": 0.7,
        }
        response = client.post("/graph/traverse", json=request_data, headers=auth_headers)

        data = assert_api_response(response)
        call_kwargs = mock_graph_repo.traverse.call_args[1]
        assert call_kwargs["min_confidence"] == 0.7

    def test_traverse_missing_start_entity_returns_422(self, client, auth_headers):
        """Test that missing start_entity returns validation error."""
        request_data = {
            "max_depth": 3,
        }
        response = client.post("/graph/traverse", json=request_data, headers=auth_headers)

        assert response.status_code == 422

    def test_traverse_default_values(self, client, auth_headers, mock_graph_repo):
        """Test that default values are applied correctly."""
        mock_graph_repo.traverse = AsyncMock(return_value=SAMPLE_TRAVERSE_RESULT)

        request_data = {
            "start_entity": "EntityA",
            "max_depth": 3,
        }
        response = client.post("/graph/traverse", json=request_data, headers=auth_headers)

        data = assert_api_response(response)
        call_kwargs = mock_graph_repo.traverse.call_args[1]
        # Defaults
        assert call_kwargs["relation_types"] is None
        assert call_kwargs["max_results"] == 100
        assert call_kwargs["timeout_seconds"] == 10
        assert call_kwargs["return_paths"] is False
        assert call_kwargs["mode"] == "full"
        assert call_kwargs["min_confidence"] is None
