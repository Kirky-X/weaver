# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for graph entity listing endpoint.

 regression: the 500 handler previously embedded ``str(exc)`` in the
HTTP detail, leaking internal paths/SQL. It must return a generic message and
log the full exception server-side.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.endpoints.graph.graph import router
from api.dependencies import get_graph_pool, get_graph_pool_type
from api.middleware.auth import verify_api_key

# Simulated internal exception text that must never reach the client.
_INTERNAL_EXC_TEXT = "postgresql://admin:pw@internal_table — SELECT * failed"


def _make_client(exc: Exception) -> TestClient:
    app = FastAPI()
    app.include_router(router)

    app.dependency_overrides[verify_api_key] = lambda: "test-key"
    app.dependency_overrides[get_graph_pool_type] = lambda: "neo4j"

    pool = MagicMock()
    pool.database_type = "neo4j"
    pool.execute_query = AsyncMock(side_effect=exc)
    app.dependency_overrides[get_graph_pool] = lambda: pool

    return TestClient(app, raise_server_exceptions=False)


class TestListEntitiesErrorHandling:
    def test_query_failure_returns_500_generic_detail(self) -> None:
        client = _make_client(Exception(_INTERNAL_EXC_TEXT))

        resp = client.get("/graph/entities")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal error while listing entities."

    def test_query_failure_does_not_leak_exception_text(self) -> None:
        client = _make_client(Exception(_INTERNAL_EXC_TEXT))

        body = client.get("/graph/entities").text

        assert "internal_table" not in body
        assert "SELECT" not in body
        assert "postgresql" not in body
        assert "admin:pw" not in body

    def test_failure_with_type_filter_also_generic(self) -> None:
        client = _make_client(Exception(_INTERNAL_EXC_TEXT))

        resp = client.get("/graph/entities", params={"entity_type": "人物", "limit": 5})

        assert resp.status_code == 500
        assert "internal_table" not in resp.text
