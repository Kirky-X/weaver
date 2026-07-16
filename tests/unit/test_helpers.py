# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for tests/helpers.py factory functions."""

import asyncio
from unittest.mock import AsyncMock

from tests.helpers import (
    create_mock_embedding,
    create_mock_relational_pool,
    create_test_client,
)


class TestCreateMockRelationalPool:
    """Tests for create_mock_relational_pool()."""

    def test_pool_has_session_method(self):
        pool = create_mock_relational_pool()
        assert hasattr(pool, "session")
        session = pool.session()
        assert session is not None

    def test_session_supports_async_context_manager(self):
        pool = create_mock_relational_pool()
        session = pool.session()
        assert hasattr(session, "__aenter__")
        assert hasattr(session, "__aexit__")

    async def test_session_aenter_returns_session(self):
        pool = create_mock_relational_pool()
        session = pool.session()
        result = await session.__aenter__()
        assert result is session

    async def test_session_aexit_returns_none(self):
        pool = create_mock_relational_pool()
        session = pool.session()
        result = await session.__aexit__(None, None, None)
        assert result is None

    def test_session_has_async_methods(self):
        pool = create_mock_relational_pool()
        session = pool.session()
        for method_name in ("execute", "commit", "rollback", "refresh", "flush", "close"):
            assert hasattr(session, method_name)
            assert isinstance(getattr(session, method_name), AsyncMock)

    def test_session_has_sync_methods(self):
        pool = create_mock_relational_pool()
        session = pool.session()
        for method_name in ("add", "delete"):
            assert hasattr(session, method_name)


class TestCreateTestClient:
    """Tests for create_test_client()."""

    def test_creates_client_with_router(self):
        from fastapi import APIRouter

        router = APIRouter()

        @router.get("/test")
        def test_endpoint():
            return {"ok": True}

        client = create_test_client(router)
        response = client.get("/test")
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_includes_verify_api_key_override(self):
        from fastapi import APIRouter

        router = APIRouter()

        @router.get("/protected")
        def protected_endpoint():
            return {"ok": True}

        client = create_test_client(router)
        response = client.get("/protected")
        # Should not get 401/403 since verify_api_key is overridden
        assert response.status_code == 200

    def test_custom_dependency_overrides(self):
        from fastapi import APIRouter, Depends

        router = APIRouter()

        def get_value():
            return "original"

        @router.get("/value")
        def value_endpoint(value: str = Depends(get_value)):
            return {"value": value}

        client = create_test_client(router, dependency_overrides={get_value: lambda: "overridden"})
        response = client.get("/value")
        assert response.status_code == 200
        assert response.json() == {"value": "overridden"}


class TestCreateMockEmbedding:
    """Tests for create_mock_embedding()."""

    def test_default_dimensions_and_fill(self):
        result = create_mock_embedding()
        assert len(result) == 1536
        assert all(v == 0.1 for v in result)

    def test_custom_dimensions_and_fill(self):
        result = create_mock_embedding(dimensions=384, fill_value=0.2)
        assert len(result) == 384
        assert all(v == 0.2 for v in result)

    def test_returns_list_of_floats(self):
        result = create_mock_embedding(dimensions=5, fill_value=0.5)
        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)
