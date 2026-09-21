# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""E2E tests for search endpoints (unified, local, global, drift, causal, temporal).

Contract (src/api/endpoints/content/search.py):
- Success envelope data: SearchResponse{query, answer, context_tokens,
  confidence, search_type, entities, sources, metadata}
- Missing/empty q or query → 422 (code 10001)
- Degraded environments: engine/LLM/embedding unavailable → 503 (code 50001);
  local search degrades to 200 with confidence 0.0 and degraded metadata;
  temporal falls back to substring matching (200)
- Drift without LLM → 503 "DRIFT search unavailable"
- Causal with no matches → 200, answer text, causal_chain=[], confidence 0.0
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.e2e.endpoints._kit import api_call, api_call_multi


def _assert_search_shape(data: dict, expected_type: str | None = None) -> None:
    for key in (
        "query",
        "answer",
        "context_tokens",
        "confidence",
        "search_type",
        "entities",
        "sources",
        "metadata",
    ):
        assert key in data, f"search response key {key} missing"
    assert isinstance(data["entities"], list)
    assert isinstance(data["sources"], list)
    assert isinstance(data["metadata"], dict)
    if expected_type:
        assert data["search_type"] == expected_type


@pytest.mark.e2e
class TestUnifiedSearch:
    """GET /api/v1/search."""

    def test_requires_auth(self, client: TestClient, recorder):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/search?q=x",
            "search",
            "unified_no_auth_expect_401",
            expect_status=401,
            expect_code=10002,
            expect_data=False,
        )

    def test_missing_query(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/search",
            "search",
            "unified_missing_q_expect_422",
            headers=auth_headers,
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_empty_query(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/search",
            "search",
            "unified_empty_q_expect_422",
            headers=auth_headers,
            params={"q": ""},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_limit_bounds(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/search",
            "search",
            "unified_limit_0_expect_422",
            headers=auth_headers,
            params={"q": "test", "limit": "0"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/search",
            "search",
            "unified_limit_101_expect_422",
            headers=auth_headers,
            params={"q": "test", "limit": "101"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_threshold_bounds(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/search",
            "search",
            "unified_threshold_2_expect_422",
            headers=auth_headers,
            params={"q": "test", "threshold": "2.0"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_search_degraded_or_service(self, client: TestClient, recorder, auth_headers):
        """Full stack: 200 with shape (possibly degraded). Empty index: 503."""
        body = api_call_multi(
            client,
            recorder,
            "GET",
            "/api/v1/search",
            "search",
            "unified_query",
            variants={
                200: {},
                503: {"expect_code": 50001, "expect_data": False},
            },
            headers=auth_headers,
            params={"q": "technology"},
        )
        if body and body.get("data"):
            _assert_search_shape(body["data"])
            # 0.0 ≤ confidence ≤ 1.0 always
            assert 0.0 <= body["data"]["confidence"] <= 1.0


@pytest.mark.e2e
class TestLocalGlobalSearch:
    """GET /api/v1/search/local and /global."""

    def test_local_missing_q(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/search/local",
            "search",
            "local_missing_q_expect_422",
            headers=auth_headers,
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_local_search(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/search/local",
            "search",
            "local_query",
            headers=auth_headers,
            params={"q": "economy"},
        )
        _assert_search_shape(body["data"], expected_type="local")

    def test_global_missing_q(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/search/global",
            "search",
            "global_missing_q_expect_422",
            headers=auth_headers,
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_global_search(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/search/global",
            "search",
            "global_query",
            headers=auth_headers,
            params={"q": "policy"},
        )
        _assert_search_shape(body["data"], expected_type="global")

    def test_global_community_level_bounds(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/search/global",
            "search",
            "global_level_11_expect_422",
            headers=auth_headers,
            params={"q": "x", "community_level": "11"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )


@pytest.mark.e2e
class TestDriftSearch:
    """POST /api/v1/search/drift."""

    def test_missing_query(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/search/drift",
            "search",
            "drift_missing_query_expect_422",
            headers=auth_headers,
            json_data={},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_param_bounds(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/search/drift",
            "search",
            "drift_confidence_above_1_expect_422",
            headers=auth_headers,
            json_data={"query": "x", "confidence_threshold": 1.5},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/search/drift",
            "search",
            "drift_primer_k_0_expect_422",
            headers=auth_headers,
            json_data={"query": "x", "primer_k": 0},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_drift_available_or_unavailable(self, client: TestClient, recorder, auth_headers):
        """503 without LLM (code 50001); 200 with full payload otherwise."""
        body = api_call_multi(
            client,
            recorder,
            "POST",
            "/api/v1/search/drift",
            "search",
            "drift_query",
            variants={
                200: {},
                503: {"expect_code": 50001, "expect_data": False},
            },
            headers=auth_headers,
            json_data={"query": "impact analysis"},
        )
        if body and body.get("data"):
            data = body["data"]
            for key in ("query", "answer", "confidence", "search_type", "hierarchy"):
                assert key in data, f"drift key {key} missing"
            assert data["search_type"] == "drift"


@pytest.mark.e2e
class TestCausalSearch:
    """POST /api/v1/search/causal."""

    def test_missing_query(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/search/causal",
            "search",
            "causal_missing_query_expect_422",
            headers=auth_headers,
            json_data={},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_max_depth_bounds(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/search/causal",
            "search",
            "causal_depth_11_expect_422",
            headers=auth_headers,
            json_data={"query": "x", "max_depth": 11},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_causal_empty_or_unavailable(self, client: TestClient, recorder, auth_headers):
        """200: empty chain + zero confidence (empty graph) or degraded answers;
        503: embedding service missing (code 50001)."""
        body = api_call_multi(
            client,
            recorder,
            "POST",
            "/api/v1/search/causal",
            "search",
            "causal_query",
            variants={
                200: {},
                503: {"expect_code": 50001, "expect_data": False},
            },
            headers=auth_headers,
            json_data={"query": "why did prices rise"},
        )
        if body and body.get("data"):
            data = body["data"]
            for key in ("query", "answer", "causal_chain", "confidence", "metadata"):
                assert key in data, f"causal key {key} missing"
            assert isinstance(data["causal_chain"], list)
            assert 0.0 <= data["confidence"] <= 1.0


@pytest.mark.e2e
class TestTemporalSearch:
    """POST /api/v1/search/temporal."""

    def test_missing_query(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/search/temporal",
            "search",
            "temporal_missing_query_expect_422",
            headers=auth_headers,
            json_data={},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_invalid_time_range(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/search/temporal",
            "search",
            "temporal_bad_time_range_expect_400",
            headers=auth_headers,
            json_data={"query": "x", "time_range": "yesterday"},
            expect_status=400,
            expect_code=10001,
            expect_data=False,
        )
        assert "time_range" in body["message"]

    def test_temporal_degrades_without_embedding(self, client: TestClient, recorder, auth_headers):
        """Embedding-less environments degrade to substring matching (200);
        graph pool missing → 503."""
        body = api_call_multi(
            client,
            recorder,
            "POST",
            "/api/v1/search/temporal",
            "search",
            "temporal_query",
            variants={
                200: {},
                503: {"expect_code": 50001, "expect_data": False},
            },
            headers=auth_headers,
            json_data={"query": "meeting", "time_range": "7d", "limit": 5},
        )
        if body and body.get("data"):
            data = body["data"]
            for key in ("query", "events", "time_range", "metadata"):
                assert key in data, f"temporal key {key} missing"
            assert isinstance(data["events"], list)
            assert "window_days" in data["time_range"]
