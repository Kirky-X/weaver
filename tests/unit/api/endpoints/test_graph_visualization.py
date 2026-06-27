# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for graph visualization endpoint security."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import assert_api_response, create_test_client


def test_hops_whitelist_mapping():
    """Verify hop patterns are correctly mapped."""
    from api.endpoints.graph.graph_visualization import _HOPS_PATTERNS

    assert _HOPS_PATTERNS[1] == "*1..1"
    assert _HOPS_PATTERNS[2] == "*1..2"
    assert _HOPS_PATTERNS[3] == "*1..3"
    assert _HOPS_PATTERNS[4] == "*1..4"


def test_hops_whitelist_prevents_injection():
    """Verify that invalid hop values use safe default."""
    from api.endpoints.graph.graph_visualization import _HOPS_PATTERNS

    # Invalid values should not be in whitelist
    assert 0 not in _HOPS_PATTERNS
    assert 5 not in _HOPS_PATTERNS
    assert -1 not in _HOPS_PATTERNS

    # get() returns None for invalid keys (default is "*1..2")
    assert _HOPS_PATTERNS.get(0) is None
    assert _HOPS_PATTERNS.get(5) is None
    assert _HOPS_PATTERNS.get(-1) is None


def test_hops_pattern_format():
    """Verify hop patterns use correct Cypher syntax."""
    from api.endpoints.graph.graph_visualization import _HOPS_PATTERNS

    for hops, pattern in _HOPS_PATTERNS.items():
        # Pattern should start with * and contain range
        assert pattern.startswith("*")
        assert ".." in pattern
        # Range should match the key
        expected_range = f"1..{hops}"
        assert expected_range in pattern


# ─────────────────────────────────────────────────────────────────────
# Fixtures for Extended Tests
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_graph_repo():
    """Create mock GraphRepository for testing."""
    repo = MagicMock()
    repo.get_visualization_nodes = AsyncMock(return_value=[])
    repo.get_visualization_edges = AsyncMock(return_value=[])
    repo.get_subgraph_nodes = AsyncMock(return_value=[])
    repo.get_subgraph_edges = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def client(mock_graph_repo):
    """Create TestClient for graph visualization endpoints."""
    from api.dependencies import get_graph_repo
    from api.endpoints.graph.graph_visualization import router

    test_client = create_test_client(
        router, dependency_overrides={get_graph_repo: lambda: mock_graph_repo}
    )
    with test_client:
        yield test_client


# ─────────────────────────────────────────────────────────────────────
# Extended Tests for Coverage (Lines 92-154, 182-230)
# ─────────────────────────────────────────────────────────────────────


class TestGraphVisualizationSnapshot:
    """Test graph visualization snapshot endpoint (GET /) - lines 92-154."""

    @pytest.mark.asyncio
    async def test_should_return_empty_graph_when_no_nodes(
        self, client, auth_headers, mock_graph_repo
    ):
        """Test empty graph response when no nodes exist."""
        mock_graph_repo.get_visualization_nodes = AsyncMock(return_value=[])

        response = client.get("/graph/visualization", headers=auth_headers)

        data = assert_api_response(response)
        assert data["data"]["nodes"] == []
        assert data["data"]["edges"] == []
        assert data["data"]["metadata"]["total_nodes"] == 0

    @pytest.mark.asyncio
    async def test_should_return_nodes_and_edges(self, client, auth_headers, mock_graph_repo):
        """Test successful graph snapshot with nodes and edges."""
        nodes_data = [
            {"id": "n1", "label": "Entity 1", "type": "PERSON", "description": "Test", "degree": 5},
            {"id": "n2", "label": "Entity 2", "type": "ORG", "description": "Test 2", "degree": 3},
        ]
        edges_data = [
            {"source": "n1", "target": "n2", "relation_type": "RELATED_TO", "weight": 0.8},
        ]

        mock_graph_repo.get_visualization_nodes = AsyncMock(return_value=nodes_data)
        mock_graph_repo.get_visualization_edges = AsyncMock(return_value=edges_data)

        response = client.get("/graph/visualization", headers=auth_headers)

        data = assert_api_response(response)
        assert len(data["data"]["nodes"]) == 2
        assert len(data["data"]["edges"]) == 1
        assert data["data"]["nodes"][0]["id"] == "n1"
        assert data["data"]["nodes"][0]["type"] == "PERSON"
        assert data["data"]["edges"][0]["source"] == "n1"
        assert data["data"]["metadata"]["total_nodes"] == 2
        assert data["data"]["metadata"]["total_edges"] == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "limit,expected_call",
        [
            (10, 10),
            (50, 50),
            (100, 100),  # Default
            (500, 500),
        ],
    )
    async def test_should_respect_limit_parameter(
        self, client, auth_headers, mock_graph_repo, limit, expected_call
    ):
        """Test that limit parameter controls node query size."""
        mock_graph_repo.get_visualization_nodes = AsyncMock(return_value=[])

        response = client.get("/graph/visualization", params={"limit": limit}, headers=auth_headers)

        # Verify the limit was passed to the repository
        mock_graph_repo.get_visualization_nodes.assert_called_once_with(expected_call)
        assert_api_response(response)

    @pytest.mark.asyncio
    async def test_should_handle_node_query_error(self, client, auth_headers, mock_graph_repo):
        """Test graceful handling when node query fails."""
        mock_graph_repo.get_visualization_nodes = AsyncMock(
            side_effect=Exception("Graph connection failed")
        )

        response = client.get("/graph/visualization", headers=auth_headers)

        # Should return 200 with empty graph and error in metadata
        data = assert_api_response(response)
        assert data["data"]["nodes"] == []
        assert data["data"]["edges"] == []
        assert "error" in data["data"]["metadata"]
        assert "Graph connection failed" in data["data"]["metadata"]["error"]

    @pytest.mark.asyncio
    async def test_should_handle_edge_query_error(self, client, auth_headers, mock_graph_repo):
        """Test graceful handling when edge query fails but nodes succeed."""
        nodes_data = [
            {"id": "n1", "label": "Entity 1", "type": "PERSON", "degree": 2},
        ]
        mock_graph_repo.get_visualization_nodes = AsyncMock(return_value=nodes_data)
        mock_graph_repo.get_visualization_edges = AsyncMock(
            side_effect=Exception("Edge query failed")
        )

        response = client.get("/graph/visualization", headers=auth_headers)

        # Should return nodes but no edges, with error in metadata
        data = assert_api_response(response)
        assert len(data["data"]["nodes"]) == 1
        assert data["data"]["edges"] == []
        assert "error" in data["data"]["metadata"]
        assert data["data"]["metadata"]["total_nodes"] == 1
        assert data["data"]["metadata"]["total_edges"] == 0

    @pytest.mark.asyncio
    async def test_should_calculate_edge_limit_correctly(
        self, client, auth_headers, mock_graph_repo
    ):
        """Test that edge limit is calculated as limit * 3."""
        nodes_data = [
            {"id": "n1", "label": "Entity 1", "type": "PERSON", "degree": 2},
        ]
        mock_graph_repo.get_visualization_nodes = AsyncMock(return_value=nodes_data)
        mock_graph_repo.get_visualization_edges = AsyncMock(return_value=[])

        response = client.get("/graph/visualization", params={"limit": 50}, headers=auth_headers)

        # Edge limit should be 50 * 3 = 150
        mock_graph_repo.get_visualization_edges.assert_called_once_with(["n1"], 150)
        assert_api_response(response)

    @pytest.mark.asyncio
    async def test_should_return_node_properties(self, client, auth_headers, mock_graph_repo):
        """Test that node properties are correctly mapped."""
        nodes_data = [
            {
                "id": "n1",
                "label": "Test Entity",
                "type": "GPE",
                "description": "A test location",
                "degree": 10,
            },
        ]
        mock_graph_repo.get_visualization_nodes = AsyncMock(return_value=nodes_data)
        mock_graph_repo.get_visualization_edges = AsyncMock(return_value=[])

        response = client.get("/graph/visualization", headers=auth_headers)

        data = assert_api_response(response)
        node = data["data"]["nodes"][0]
        assert node["id"] == "n1"
        assert node["label"] == "Test Entity"
        assert node["type"] == "GPE"
        assert node["properties"]["description"] == "A test location"
        assert node["properties"]["degree"] == 10

    @pytest.mark.asyncio
    async def test_should_return_edge_properties(self, client, auth_headers, mock_graph_repo):
        """Test that edge properties are correctly mapped."""
        nodes_data = [
            {"id": "n1", "label": "E1", "type": "PERSON", "degree": 1},
            {"id": "n2", "label": "E2", "type": "PERSON", "degree": 1},
        ]
        edges_data = [
            {
                "source": "n1",
                "target": "n2",
                "relation_type": "KNOWS",
                "weight": 0.95,
            },
        ]
        mock_graph_repo.get_visualization_nodes = AsyncMock(return_value=nodes_data)
        mock_graph_repo.get_visualization_edges = AsyncMock(return_value=edges_data)

        response = client.get("/graph/visualization", headers=auth_headers)

        data = assert_api_response(response)
        edge = data["data"]["edges"][0]
        assert edge["source"] == "n1"
        assert edge["target"] == "n2"
        assert edge["relation_type"] == "KNOWS"
        assert edge["weight"] == 0.95


class TestSubgraphExtraction:
    """Test subgraph extraction endpoint (POST /) - lines 182-230."""

    @pytest.mark.asyncio
    async def test_should_extract_subgraph_successfully(
        self, client, auth_headers, mock_graph_repo
    ):
        """Test successful subgraph extraction."""
        nodes_data = [
            {"id": "n1", "label": "Center", "type": "PERSON", "description": "Center entity"},
            {"id": "n2", "label": "Related", "type": "ORG", "description": "Related entity"},
        ]
        edges_data = [
            {"source": "n1", "target": "n2", "relation_type": "WORKS_AT", "weight": 1.0},
        ]

        mock_graph_repo.get_subgraph_nodes = AsyncMock(return_value=nodes_data)
        mock_graph_repo.get_subgraph_edges = AsyncMock(return_value=edges_data)

        request_data = {
            "center_entity": "Test Person",
            "max_hops": 2,
        }
        response = client.post("/graph/visualization", json=request_data, headers=auth_headers)

        data = assert_api_response(response)
        assert len(data["data"]["nodes"]) == 2
        assert len(data["data"]["edges"]) == 1
        assert data["data"]["metadata"]["center"] == "Test Person"
        assert data["data"]["metadata"]["max_hops"] == 2
        assert data["data"]["metadata"]["total_nodes"] == 2
        assert data["data"]["metadata"]["total_edges"] == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "max_hops,expected_pattern",
        [
            (1, "*1..1"),
            (2, "*1..2"),
            (3, "*1..3"),
            (4, "*1..4"),
        ],
    )
    async def test_should_use_correct_hop_pattern(
        self, client, auth_headers, mock_graph_repo, max_hops, expected_pattern
    ):
        """Test that correct hop pattern is used for different max_hops values."""
        mock_graph_repo.get_subgraph_nodes = AsyncMock(return_value=[])

        request_data = {
            "center_entity": "Test Entity",
            "max_hops": max_hops,
        }

        # Will return 404 since no nodes found, but we can verify the call
        try:
            response = client.post("/graph/visualization", json=request_data, headers=auth_headers)
        except Exception:
            pass  # 404 is expected when no nodes

        # Verify the hop pattern was passed correctly
        mock_graph_repo.get_subgraph_nodes.assert_called_once()
        call_kwargs = mock_graph_repo.get_subgraph_nodes.call_args[1]
        assert call_kwargs["hop_pattern"] == expected_pattern

    @pytest.mark.asyncio
    async def test_should_filter_by_include_types(self, client, auth_headers, mock_graph_repo):
        """Test subgraph extraction with include_types filter."""
        nodes_data = [
            {"id": "n1", "label": "Person", "type": "PERSON", "description": "Test"},
        ]
        mock_graph_repo.get_subgraph_nodes = AsyncMock(return_value=nodes_data)
        mock_graph_repo.get_subgraph_edges = AsyncMock(return_value=[])

        request_data = {
            "center_entity": "Test",
            "max_hops": 2,
            "include_types": ["PERSON", "ORG"],
        }
        response = client.post("/graph/visualization", json=request_data, headers=auth_headers)

        # Verify include_types was passed
        call_kwargs = mock_graph_repo.get_subgraph_nodes.call_args[1]
        assert call_kwargs["include_types"] == ["PERSON", "ORG"]
        assert_api_response(response)

    @pytest.mark.asyncio
    async def test_should_filter_by_exclude_types(self, client, auth_headers, mock_graph_repo):
        """Test subgraph extraction with exclude_types filter."""
        nodes_data = [
            {"id": "n1", "label": "Person", "type": "PERSON", "description": "Test"},
        ]
        mock_graph_repo.get_subgraph_nodes = AsyncMock(return_value=nodes_data)
        mock_graph_repo.get_subgraph_edges = AsyncMock(return_value=[])

        request_data = {
            "center_entity": "Test",
            "max_hops": 2,
            "exclude_types": ["GPE"],
        }
        response = client.post("/graph/visualization", json=request_data, headers=auth_headers)

        # Verify exclude_types was passed
        call_kwargs = mock_graph_repo.get_subgraph_nodes.call_args[1]
        assert call_kwargs["exclude_types"] == ["GPE"]
        assert_api_response(response)

    @pytest.mark.asyncio
    async def test_should_return_400_when_max_hops_invalid(
        self, client, auth_headers, mock_graph_repo
    ):
        """Test that invalid max_hops returns 400."""
        # Pydantic validation should catch this before endpoint logic
        request_data = {
            "center_entity": "Test",
            "max_hops": 5,  # Invalid: > 4
        }
        response = client.post("/graph/visualization", json=request_data, headers=auth_headers)

        # Should return 422 (validation error) or 400
        assert response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_should_return_400_when_max_hops_zero(
        self, client, auth_headers, mock_graph_repo
    ):
        """Test that zero max_hops returns validation error."""
        request_data = {
            "center_entity": "Test",
            "max_hops": 0,  # Invalid: < 1
        }
        response = client.post("/graph/visualization", json=request_data, headers=auth_headers)

        assert response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_should_return_200_empty_graph_when_no_nodes_found(
        self, client, auth_headers, mock_graph_repo
    ):
        """REM-007: Empty subgraph returns 200 OK with empty graph (not 404).

        Entity exists in graph but has no neighbors within max_hops.
        Consistent with GET /graph/visualization and exception path behavior.
        """
        mock_graph_repo.get_subgraph_nodes = AsyncMock(return_value=[])

        request_data = {
            "center_entity": "NonExistent",
            "max_hops": 2,
        }
        response = client.post("/graph/visualization", json=request_data, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        payload = data.get("data", data)
        assert payload["nodes"] == []
        assert payload["edges"] == []
        assert payload["metadata"]["total_nodes"] == 0

    @pytest.mark.asyncio
    async def test_should_return_200_empty_graph_when_subgraph_query_fails(
        self, client, auth_headers, mock_graph_repo
    ):
        """REM-007: Subgraph query failure returns 200 OK with empty graph (not 404).

        Distinguishes "entity not found" (which would be 404) from "query error"
        (database connectivity, etc.). Returns empty graph with error metadata,
        consistent with GET /graph/visualization behavior.
        """
        mock_graph_repo.get_subgraph_nodes = AsyncMock(side_effect=Exception("Query failed"))

        request_data = {
            "center_entity": "Test",
            "max_hops": 2,
        }
        response = client.post("/graph/visualization", json=request_data, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        payload = data.get("data", data)
        assert payload["nodes"] == []
        assert payload["edges"] == []
        assert "error" in payload["metadata"]

    @pytest.mark.asyncio
    async def test_should_use_default_max_hops(self, client, auth_headers, mock_graph_repo):
        """Test that max_hops defaults to 2 when not specified."""
        mock_graph_repo.get_subgraph_nodes = AsyncMock(return_value=[])

        request_data = {
            "center_entity": "Test",
            # max_hops not specified, should default to 2
        }
        try:
            response = client.post("/graph/visualization", json=request_data, headers=auth_headers)
        except Exception:
            pass  # 404 expected

        # Verify default hop pattern (*1..2) was used
        call_kwargs = mock_graph_repo.get_subgraph_nodes.call_args[1]
        assert call_kwargs["hop_pattern"] == "*1..2"


class TestVisualizationErrors:
    """Test error handling in visualization endpoints."""

    @pytest.mark.asyncio
    async def test_should_handle_missing_api_key(self, client):
        """Test that missing API key returns 401."""
        from api.dependencies import get_graph_repo
        from api.endpoints.graph.graph_visualization import router
        from api.middleware.auth import verify_api_key

        # Create client with repo override but then remove auth override
        unauthed_client = create_test_client(
            router,
            dependency_overrides={get_graph_repo: lambda: MagicMock()},
        )
        unauthed_client.app.dependency_overrides.pop(verify_api_key, None)

        with unauthed_client:
            response = unauthed_client.get("/graph/visualization")
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_should_handle_node_with_missing_fields(
        self, client, auth_headers, mock_graph_repo
    ):
        """Test handling of nodes with missing optional fields."""
        nodes_data = [
            {"id": "n1", "label": "Test", "type": "PERSON"},  # Missing description and degree
        ]
        mock_graph_repo.get_visualization_nodes = AsyncMock(return_value=nodes_data)
        mock_graph_repo.get_visualization_edges = AsyncMock(return_value=[])

        response = client.get("/graph/visualization", headers=auth_headers)

        data = assert_api_response(response)
        assert len(data["data"]["nodes"]) == 1
        # Should have default values
        assert "properties" in data["data"]["nodes"][0]

    @pytest.mark.asyncio
    async def test_should_handle_edge_with_missing_weight(
        self, client, auth_headers, mock_graph_repo
    ):
        """Test handling of edges with missing weight field."""
        nodes_data = [
            {"id": "n1", "label": "E1", "type": "PERSON", "degree": 1},
            {"id": "n2", "label": "E2", "type": "PERSON", "degree": 1},
        ]
        edges_data = [
            {"source": "n1", "target": "n2", "relation_type": "RELATED_TO"},  # No weight
        ]
        mock_graph_repo.get_visualization_nodes = AsyncMock(return_value=nodes_data)
        mock_graph_repo.get_visualization_edges = AsyncMock(return_value=edges_data)

        response = client.get("/graph/visualization", headers=auth_headers)

        data = assert_api_response(response)
        assert len(data["data"]["edges"]) == 1
        # Weight should be None or absent
        edge = data["data"]["edges"][0]
        assert edge.get("weight") is None

    @pytest.mark.asyncio
    async def test_validation_error_for_invalid_request_body(self, client, auth_headers):
        """Test validation error for invalid POST request body."""
        # Missing required field: center_entity
        request_data = {
            "max_hops": 2,
        }
        response = client.post("/graph/visualization", json=request_data, headers=auth_headers)

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_error_message_truncation(self, client, auth_headers, mock_graph_repo):
        """Test that error messages are truncated to 200 characters."""
        long_error = "A" * 300
        mock_graph_repo.get_visualization_nodes = AsyncMock(side_effect=Exception(long_error))

        response = client.get("/graph/visualization", headers=auth_headers)

        data = assert_api_response(response)
        error_msg = data["data"]["metadata"]["error"]
        assert len(error_msg) <= 200


class TestResponseModels:
    """Test Pydantic response models."""

    def test_node_response_model(self):
        """Test NodeResponse model creation."""
        from api.endpoints.graph.graph_visualization import NodeResponse

        node = NodeResponse(
            id="n1",
            label="Test Node",
            type="PERSON",
            properties={"description": "Test", "degree": 5},
        )
        assert node.id == "n1"
        assert node.label == "Test Node"
        assert node.type == "PERSON"
        assert node.properties["description"] == "Test"

    def test_edge_response_model(self):
        """Test EdgeResponse model creation."""
        from api.endpoints.graph.graph_visualization import EdgeResponse

        edge = EdgeResponse(
            source="n1",
            target="n2",
            relation_type="RELATED_TO",
            weight=0.8,
            properties={},
        )
        assert edge.source == "n1"
        assert edge.target == "n2"
        assert edge.relation_type == "RELATED_TO"
        assert edge.weight == 0.8

    def test_graph_snapshot_response_model(self):
        """Test GraphSnapshotResponse model creation."""
        from api.endpoints.graph.graph_visualization import (
            EdgeResponse,
            GraphSnapshotResponse,
            NodeResponse,
        )

        nodes = [NodeResponse(id="n1", label="N1", type="PERSON")]
        edges = [EdgeResponse(source="n1", target="n2", relation_type="RELATED_TO")]
        metadata = {"total_nodes": 1, "total_edges": 1}

        snapshot = GraphSnapshotResponse(
            nodes=nodes,
            edges=edges,
            metadata=metadata,
        )
        assert len(snapshot.nodes) == 1
        assert len(snapshot.edges) == 1
        assert snapshot.metadata["total_nodes"] == 1

    def test_subgraph_request_model_validation(self):
        """Test SubgraphRequest model validation."""
        from api.endpoints.graph.graph_visualization import SubgraphRequest

        # Valid request
        request = SubgraphRequest(
            center_entity="Test",
            max_hops=3,
            include_types=["PERSON"],
            exclude_types=["ORG"],
        )
        assert request.center_entity == "Test"
        assert request.max_hops == 3
        assert request.include_types == ["PERSON"]
        assert request.exclude_types == ["ORG"]

    def test_subgraph_request_default_values(self):
        """Test SubgraphRequest model default values."""
        from api.endpoints.graph.graph_visualization import SubgraphRequest

        request = SubgraphRequest(center_entity="Test")
        assert request.max_hops == 2  # Default
        assert request.include_types is None
        assert request.exclude_types is None
