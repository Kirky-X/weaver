# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""E2E tests for knowledge-graph endpoints (entities, relations, traverse,
metrics, visualization).

Contract (src/api/endpoints/graph/):
- GET /entities/{name}, GET /relations (by entity), GET /articles/{id}/graph
  return 404 for unknown resources
- GET /relations/search and POST /traverse return 200 with empty results for
  unknown entities (no existence check by design)
- POST /traverse: max_depth 1-6, max_results 1-1000, timeout 1-10,
  mode regex ^(full|aggregate)$; unknown start → 200 + zeroed statistics
- GET /graph/metrics: view=health (default)|full; community → 400 (moved);
  unknown view → 400; excluded `include` fields are null (not 0)
- GET /visualization: limit ge=10 (unusual lower bound!); graph errors
  degrade to 200 + metadata.error
- POST /visualization: unknown center entity → 200 + empty graph + message
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.e2e.endpoints._kit import api_call

METRICS_INCLUDE_FIELDS = ("components", "orphans", "high_degree", "modularity", "distributions")


@pytest.mark.e2e
class TestGraphAuth:
    """Every graph endpoint requires a regular API key."""

    def test_entities_requires_auth(self, client: TestClient, recorder):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/entities",
            "graph",
            "entities_no_auth_expect_401",
            expect_status=401,
            expect_code=10002,
            expect_data=False,
        )

    def test_traverse_requires_auth(self, client: TestClient, recorder):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/graph/traverse",
            "graph",
            "traverse_no_auth_expect_401",
            json_data={"start_entity": "x"},
            expect_status=401,
            expect_code=10002,
            expect_data=False,
        )


@pytest.mark.e2e
class TestGraphEntities:
    """GET /api/v1/graph/entities[/{name}]."""

    def test_list_entities_empty_graph(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/entities",
            "graph",
            "entities_list",
            headers=auth_headers,
        )
        assert isinstance(body["data"], list)

    def test_list_entities_limit_bounds(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/entities",
            "graph",
            "entities_limit_0_expect_422",
            headers=auth_headers,
            params={"limit": "0"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/entities",
            "graph",
            "entities_limit_101_expect_422",
            headers=auth_headers,
            params={"limit": "101"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_get_entity_not_found(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/entities/no-such-entity",
            "graph",
            "entity_not_found_expect_404",
            headers=auth_headers,
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )
        assert "no-such-entity" in body["message"]

    def test_get_entity_limit_bounds(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/entities/x",
            "graph",
            "entity_limit_0_expect_422",
            headers=auth_headers,
            params={"limit": "0"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )


@pytest.mark.e2e
class TestGraphArticle:
    """GET /api/v1/graph/articles/{article_id}/graph."""

    def test_article_not_in_graph(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/articles/no-such-article/graph",
            "graph",
            "article_graph_not_found_expect_404",
            headers=auth_headers,
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )
        assert "no-such-article" in body["message"]


@pytest.mark.e2e
class TestGraphRelations:
    """GET /api/v1/graph/relations and /relations/search."""

    def test_relations_entity_required(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/relations",
            "graph",
            "relations_missing_entity_expect_422",
            headers=auth_headers,
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_relations_unknown_entity_404(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/relations",
            "graph",
            "relations_unknown_entity_expect_404",
            headers=auth_headers,
            params={"entity": "no-such-entity"},
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )

    def test_relations_search_unknown_entity_empty(
        self, client: TestClient, recorder, auth_headers
    ):
        """No existence check by design: unknown entity → 200 []."""
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/relations/search",
            "graph",
            "relations_search_unknown_entity_empty",
            headers=auth_headers,
            params={"entity": "no-such-entity"},
        )
        assert body["data"] == []

    def test_relations_search_limit_bounds(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/relations/search",
            "graph",
            "relations_search_limit_201_expect_422",
            headers=auth_headers,
            params={"entity": "x", "limit": "201"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )


@pytest.mark.e2e
class TestGraphTraverse:
    """POST /api/v1/graph/traverse."""

    def test_missing_start_entity(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/graph/traverse",
            "graph",
            "traverse_missing_start_expect_422",
            headers=auth_headers,
            json_data={},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("max_depth", 0),
            ("max_depth", 7),
            ("max_results", 0),
            ("max_results", 1001),
            ("timeout_seconds", 0),
            ("timeout_seconds", 11),
        ],
    )
    def test_param_bounds(self, client: TestClient, recorder, auth_headers, field, value):
        payload = {"start_entity": "x", field: value}
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/graph/traverse",
            "graph",
            f"traverse_{field}_{value}_expect_422",
            headers=auth_headers,
            json_data=payload,
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_invalid_mode(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/graph/traverse",
            "graph",
            "traverse_invalid_mode_expect_422",
            headers=auth_headers,
            json_data={"start_entity": "x", "mode": "bfs"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_traverse_unknown_start_empty_result(self, client: TestClient, recorder, auth_headers):
        """Unknown start → 200 with empty results and zeroed statistics."""
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/graph/traverse",
            "graph",
            "traverse_unknown_start",
            headers=auth_headers,
            json_data={"start_entity": "no-such-entity"},
        )
        data = body["data"]
        assert data["results"] == []
        stats = data["statistics"]
        assert stats["nodes_visited"] == 0
        assert stats["edges_traversed"] == 0
        assert "execution_time_ms" in stats


@pytest.mark.e2e
class TestGraphMetrics:
    """GET /api/v1/graph/metrics."""

    def test_health_view(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/metrics",
            "graph_metrics",
            "metrics_health_default",
            headers=auth_headers,
        )
        data = body["data"]
        for key in (
            "health_score",
            "status",
            "entity_count",
            "relationship_count",
            "orphan_ratio",
            "connectedness",
            "average_degree",
        ):
            assert key in data, f"metrics health key {key} missing"
        assert 0 <= data["health_score"] <= 100
        assert 0.0 <= data["orphan_ratio"] <= 1.0
        assert 0.0 <= data["connectedness"] <= 1.0

    def test_full_view(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/metrics",
            "graph_metrics",
            "metrics_full",
            headers=auth_headers,
            params={"view": "full"},
        )
        data = body["data"]
        for key in ("total_entities", "total_relationships", "connected_components", "computed_at"):
            assert key in data, f"metrics full key {key} missing"

    def test_community_view_moved(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/metrics",
            "graph_metrics",
            "metrics_community_view_expect_400",
            headers=auth_headers,
            params={"view": "community"},
            expect_status=400,
            expect_code=10001,
            expect_data=False,
        )
        # Migration guidance points at the replacement endpoint
        assert (
            "/api/v1/admin/communities/health" in body["message"]
            or "communities/health" in body["message"]
        )

    def test_invalid_view(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/metrics",
            "graph_metrics",
            "metrics_invalid_view_expect_400",
            headers=auth_headers,
            params={"view": "bogus"},
            expect_status=400,
            expect_code=10001,
            expect_data=False,
        )
        assert "Invalid view" in body["message"]

    def test_include_subset_nulls_excluded(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/metrics",
            "graph_metrics",
            "metrics_full_include_components",
            headers=auth_headers,
            params={"view": "full", "include": "components"},
        )
        data = body["data"]
        assert data["connected_components"] is not None
        # Excluded sections are null, never fabricated zeros
        assert data.get("modularity_score") is None
        assert data.get("orphan_entities") is None

    def test_include_unknown_value_filters_everything(
        self, client: TestClient, recorder, auth_headers
    ):
        """Unknown include values are not rejected; they match nothing, so
        every optional section is null (documented tolerance, not a 400)."""
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/metrics",
            "graph_metrics",
            "metrics_full_include_unknown",
            headers=auth_headers,
            params={"view": "full", "include": "not_a_metric"},
        )
        data = body["data"]
        assert data.get("connected_components") is None
        assert data.get("modularity_score") is None
        assert data.get("orphan_entities") is None


@pytest.mark.e2e
class TestGraphVisualization:
    """GET/POST /api/v1/graph/visualization."""

    def test_get_visualization_limit_lower_bound(self, client: TestClient, recorder, auth_headers):
        # ge=10 is an unusual lower bound — pin it
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/visualization",
            "graph",
            "visualization_limit_9_expect_422",
            headers=auth_headers,
            params={"limit": "9"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/graph/visualization",
            "graph",
            "visualization_limit_10",
            headers=auth_headers,
            params={"limit": "10"},
        )
        data = body["data"]
        for key in ("nodes", "edges", "metadata"):
            assert key in data, f"visualization key {key} missing"
        assert isinstance(data["nodes"], list)
        assert isinstance(data["edges"], list)
        assert "total_nodes" in data["metadata"]

    def test_subgraph_unknown_center_empty(self, client: TestClient, recorder, auth_headers):
        """Unknown center → 200 + empty graph + message (no 404 by design)."""
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/graph/visualization",
            "graph",
            "subgraph_unknown_center_empty",
            headers=auth_headers,
            json_data={"center_entity": "no-such-entity", "max_hops": 2},
        )
        data = body["data"]
        assert data["nodes"] == []
        assert data["edges"] == []
        assert data["metadata"]["center"] == "no-such-entity"

    def test_subgraph_missing_center(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/graph/visualization",
            "graph",
            "subgraph_missing_center_expect_422",
            headers=auth_headers,
            json_data={},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_subgraph_max_hops_bounds(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/graph/visualization",
            "graph",
            "subgraph_max_hops_5_expect_422",
            headers=auth_headers,
            json_data={"center_entity": "x", "max_hops": 5},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )
