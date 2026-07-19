# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for shortcut search endpoints.

Covers 21 test cases for:
- ``GET /api/v1/search/local`` (search_local)
- ``GET /api/v1/search/global`` (search_global)

These endpoints are shortcuts for ``GET /api/v1/search?mode=local`` and
``?mode=global`` respectively, sharing the ``_execute_explicit_search`` helper.
Test matrix:
- Normal inputs (6): real entity / multi-entity / tech keyword / real article title
- Boundary (3): q=1 char, community_level=0, community_level=10
- Invalid params (5): empty/missing q, community_level=-1/11 (HTTP 422)
- Authentication (4): 401 / 403 for both endpoints
- Security (3): semicolon injection, unicode null, SQL injection
- Behavior verification (3): search_type, metadata injection, helper extraction
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from tests.fixtures.search_keywords import (
    REAL_ARTICLE_TITLES,
    REAL_CATEGORIES,
    REAL_ENTITY_NAMES,
    SQL_INJECTION_PAYLOADS,
)

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_request() -> MagicMock:
    request = MagicMock(spec=Request)
    request.client.host = "127.0.0.1"
    return request


@pytest.fixture
def mock_local_engine() -> MagicMock:
    """Mock LocalSearchEngine for /search/local tests."""
    engine = MagicMock()
    engine.search = AsyncMock(
        return_value={
            "answer": "Local search answer",
            "context_tokens": 350,
            "confidence": 0.82,
            "entities": ["华为"],
            "sources": [{"article_id": "uuid-local"}],
            "metadata": {"search_type": "local"},
        }
    )
    return engine


@pytest.fixture
def mock_global_engine() -> MagicMock:
    """Mock GlobalSearchEngine for /search/global tests."""
    engine = MagicMock()
    engine.search = AsyncMock(
        return_value={
            "answer": "Global search answer",
            "context_tokens": 1100,
            "confidence": 0.91,
            "entities": ["OpenAI"],
            "sources": [{"article_id": "uuid-global"}],
            "metadata": {"search_type": "global", "community_level": 2},
        }
    )
    return engine


@pytest.fixture
def api_key() -> str:
    return "test-api-key-32chars-long!!!!!!!"


def _build_app(
    *,
    local_engine: MagicMock | None = None,
    global_engine: MagicMock | None = None,
    skip_auth: bool = True,
) -> FastAPI:
    """Build FastAPI app with search router and dep overrides.

    Auth is bypassed by default (skip_auth=True); set skip_auth=False for
    401/403 tests.
    """
    from api.dependencies import (
        get_global_search_engine,
        get_local_search_engine,
    )
    from api.endpoints.content.search import router
    from api.middleware.auth import verify_api_key

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    if skip_auth:
        app.dependency_overrides[verify_api_key] = lambda: "test-key"
    if local_engine is not None:
        app.dependency_overrides[get_local_search_engine] = lambda: local_engine
    if global_engine is not None:
        app.dependency_overrides[get_global_search_engine] = lambda: global_engine
    return app


# ── /search/local — Normal inputs ────────────────────────────────────


class TestSearchLocalNormalInputs:
    """Verify /search/local accepts real-data queries."""

    @pytest.mark.asyncio
    async def test_search_local_with_real_entity(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Single real entity name (华为) is passed to local_engine.search."""
        from api.endpoints.content.search import search_local

        result = await search_local(
            request=mock_request,
            q=REAL_ENTITY_NAMES[0],  # "华为"
            _=api_key,
            local_engine=mock_local_engine,
        )
        assert result.data.query == REAL_ENTITY_NAMES[0]
        assert result.data.search_type == "local"
        mock_local_engine.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_local_with_multiple_entities(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Multiple entity names in a single query are accepted."""
        from api.endpoints.content.search import search_local

        q = f"{REAL_ENTITY_NAMES[0]} {REAL_ENTITY_NAMES[1]}"  # "华为 苹果"
        result = await search_local(
            request=mock_request,
            q=q,
            _=api_key,
            local_engine=mock_local_engine,
        )
        assert result.data.query == q
        # Engine received the full combined query
        call_args = mock_local_engine.search.call_args
        passed_q = call_args.args[0] if call_args.args else call_args.kwargs.get("query")
        assert passed_q == q

    @pytest.mark.asyncio
    async def test_search_local_with_tech_keyword(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Tech-domain keyword (人工智能) is accepted."""
        from api.endpoints.content.search import search_local

        await search_local(
            request=mock_request,
            q="人工智能",
            _=api_key,
            local_engine=mock_local_engine,
        )
        mock_local_engine.search.assert_called_once()


# ── /search/local — Boundary ─────────────────────────────────────────


class TestSearchLocalBoundary:
    """Verify /search/local accepts boundary inputs."""

    @pytest.mark.asyncio
    async def test_search_local_single_char_query(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        api_key: str,
    ) -> None:
        """q="华" (1 char) satisfies min_length=1."""
        from api.endpoints.content.search import search_local

        result = await search_local(
            request=mock_request,
            q="华",
            _=api_key,
            local_engine=mock_local_engine,
        )
        assert result.data.query == "华"


# ── /search/local — Invalid params (HTTP 422) ────────────────────────


class TestSearchLocalInvalidParams:
    """Verify FastAPI Query validators reject empty/missing q with 422."""

    def test_search_local_empty_q_returns_422(self, mock_local_engine: MagicMock) -> None:
        """Empty q violates min_length=1 → 422."""
        app = _build_app(local_engine=mock_local_engine, skip_auth=True)
        client = TestClient(app)
        response = client.get("/api/v1/search/local", params={"q": ""})
        assert response.status_code == 422

    def test_search_local_missing_q_returns_422(self, mock_local_engine: MagicMock) -> None:
        """Missing q parameter → 422."""
        app = _build_app(local_engine=mock_local_engine, skip_auth=True)
        client = TestClient(app)
        response = client.get("/api/v1/search/local")
        assert response.status_code == 422


# ── /search/global — Normal inputs ───────────────────────────────────


class TestSearchGlobalNormalInputs:
    """Verify /search/global accepts real-data queries."""

    @pytest.mark.asyncio
    async def test_search_global_with_real_entity(
        self,
        mock_request: MagicMock,
        mock_global_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Single real entity (马斯克) is passed to global_engine.search."""
        from api.endpoints.content.search import search_global

        result = await search_global(
            request=mock_request,
            q=REAL_ENTITY_NAMES[3],  # "马斯克"
            community_level=0,
            _=api_key,
            global_engine=mock_global_engine,
        )
        assert result.data.query == REAL_ENTITY_NAMES[3]
        assert result.data.search_type == "global"
        mock_global_engine.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_global_with_tech_category_keyword(
        self,
        mock_request: MagicMock,
        mock_global_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Tech-category keyword (大模型) accepted by global search."""
        from api.endpoints.content.search import search_global

        await search_global(
            request=mock_request,
            q="大模型",
            community_level=2,
            _=api_key,
            global_engine=mock_global_engine,
        )
        call_kwargs = mock_global_engine.search.call_args.kwargs
        assert call_kwargs["community_level"] == 2

    @pytest.mark.asyncio
    async def test_search_global_with_article_title(
        self,
        mock_request: MagicMock,
        mock_global_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Real article title as query for global search."""
        from api.endpoints.content.search import search_global

        title = REAL_ARTICLE_TITLES[4]  # 特朗普政府要求OpenAI分阶段发布GPT-5.6
        result = await search_global(
            request=mock_request,
            q=title,
            community_level=0,
            _=api_key,
            global_engine=mock_global_engine,
        )
        assert result.data.query == title


# ── /search/global — Boundary ────────────────────────────────────────


class TestSearchGlobalBoundary:
    """Verify /search/global accepts community_level boundary values."""

    @pytest.mark.asyncio
    async def test_search_global_community_level_0(
        self,
        mock_request: MagicMock,
        mock_global_engine: MagicMock,
        api_key: str,
    ) -> None:
        """community_level=0 (min) is accepted (ge=0)."""
        from api.endpoints.content.search import search_global

        await search_global(
            request=mock_request,
            q="OpenAI",
            community_level=0,
            _=api_key,
            global_engine=mock_global_engine,
        )
        assert mock_global_engine.search.call_args.kwargs["community_level"] == 0

    @pytest.mark.asyncio
    async def test_search_global_community_level_10(
        self,
        mock_request: MagicMock,
        mock_global_engine: MagicMock,
        api_key: str,
    ) -> None:
        """community_level=10 (max) is accepted (le=10)."""
        from api.endpoints.content.search import search_global

        await search_global(
            request=mock_request,
            q="OpenAI",
            community_level=10,
            _=api_key,
            global_engine=mock_global_engine,
        )
        assert mock_global_engine.search.call_args.kwargs["community_level"] == 10


# ── /search/global — Invalid params (HTTP 422) ───────────────────────


class TestSearchGlobalInvalidParams:
    """Verify FastAPI Query validators reject invalid params with 422."""

    def test_search_global_empty_q_returns_422(self, mock_global_engine: MagicMock) -> None:
        app = _build_app(global_engine=mock_global_engine, skip_auth=True)
        client = TestClient(app)
        response = client.get("/api/v1/search/global", params={"q": ""})
        assert response.status_code == 422

    def test_search_global_community_level_minus_1_returns_422(
        self, mock_global_engine: MagicMock
    ) -> None:
        """community_level=-1 violates ge=0 → 422."""
        app = _build_app(global_engine=mock_global_engine, skip_auth=True)
        client = TestClient(app)
        response = client.get(
            "/api/v1/search/global",
            params={"q": "OpenAI", "community_level": -1},
        )
        assert response.status_code == 422

    def test_search_global_community_level_11_returns_422(
        self, mock_global_engine: MagicMock
    ) -> None:
        """community_level=11 violates le=10 → 422."""
        app = _build_app(global_engine=mock_global_engine, skip_auth=True)
        client = TestClient(app)
        response = client.get(
            "/api/v1/search/global",
            params={"q": "OpenAI", "community_level": 11},
        )
        assert response.status_code == 422


# ── Authentication tests (401/403) ──────────────────────────────────


class TestSearchShortcutsAuthentication:
    """Verify /search/local and /search/global reject missing/invalid API keys."""

    def test_search_local_no_api_key_returns_401(self, mock_local_engine: MagicMock) -> None:
        """Missing X-API-Key on /search/local → 401."""
        app = _build_app(local_engine=mock_local_engine, skip_auth=False)
        with (
            patch("api.middleware.auth._get_api_key_manager", return_value=None),
            patch("container.get_settings") as mock_get_settings,
        ):
            mock_settings = MagicMock()
            mock_settings.api.get_api_key.return_value = ""
            mock_settings.api.admin_api_key = None
            mock_settings.environment = "test"
            mock_get_settings.return_value = mock_settings

            client = TestClient(app)
            response = client.get("/api/v1/search/local", params={"q": "华为"})
            assert response.status_code == 401

    def test_search_local_wrong_api_key_returns_403(self, mock_local_engine: MagicMock) -> None:
        """Invalid X-API-Key on /search/local → 403."""
        app = _build_app(local_engine=mock_local_engine, skip_auth=False)
        with (
            patch("api.middleware.auth._get_api_key_manager", return_value=None),
            patch("container.get_settings") as mock_get_settings,
        ):
            mock_settings = MagicMock()
            mock_settings.api.get_api_key.return_value = "x" * 32
            mock_settings.api.admin_api_key = None
            mock_settings.environment = "test"
            mock_get_settings.return_value = mock_settings

            client = TestClient(app)
            response = client.get(
                "/api/v1/search/local",
                params={"q": "华为"},
                headers={"X-API-Key": "wrong-key-32chars-long-!!!!!!!"},
            )
            assert response.status_code == 403

    def test_search_global_no_api_key_returns_401(self, mock_global_engine: MagicMock) -> None:
        """Missing X-API-Key on /search/global → 401."""
        app = _build_app(global_engine=mock_global_engine, skip_auth=False)
        with (
            patch("api.middleware.auth._get_api_key_manager", return_value=None),
            patch("container.get_settings") as mock_get_settings,
        ):
            mock_settings = MagicMock()
            mock_settings.api.get_api_key.return_value = ""
            mock_settings.api.admin_api_key = None
            mock_settings.environment = "test"
            mock_get_settings.return_value = mock_settings

            client = TestClient(app)
            response = client.get("/api/v1/search/global", params={"q": "OpenAI"})
            assert response.status_code == 401

    def test_search_global_wrong_api_key_returns_403(self, mock_global_engine: MagicMock) -> None:
        """Invalid X-API-Key on /search/global → 403."""
        app = _build_app(global_engine=mock_global_engine, skip_auth=False)
        with (
            patch("api.middleware.auth._get_api_key_manager", return_value=None),
            patch("container.get_settings") as mock_get_settings,
        ):
            mock_settings = MagicMock()
            mock_settings.api.get_api_key.return_value = "x" * 32
            mock_settings.api.admin_api_key = None
            mock_settings.environment = "test"
            mock_get_settings.return_value = mock_settings

            client = TestClient(app)
            response = client.get(
                "/api/v1/search/global",
                params={"q": "OpenAI"},
                headers={"X-API-Key": "wrong-key-32chars-long-!!!!!!!"},
            )
            assert response.status_code == 403


# ── Security tests ───────────────────────────────────────────────────


class TestSearchShortcutsSecurity:
    """Verify shortcut endpoints treat malicious queries as opaque strings."""

    @pytest.mark.asyncio
    async def test_search_local_semicolon_injection_safely_passed(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Cypher injection attempt (华为;MATCH(n)RETURN n) passed unchanged to engine."""
        from api.endpoints.content.search import search_local

        malicious = "华为;MATCH(n)RETURN n"
        await search_local(
            request=mock_request,
            q=malicious,
            _=api_key,
            local_engine=mock_local_engine,
        )
        call_args = mock_local_engine.search.call_args
        passed_q = call_args.args[0] if call_args.args else call_args.kwargs.get("query")
        assert passed_q == malicious

    @pytest.mark.asyncio
    async def test_search_local_unicode_null_safely_passed(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Unicode NULL character (\\u0000) in q is passed through."""
        from api.endpoints.content.search import search_local

        malicious = "华为\u0000"
        await search_local(
            request=mock_request,
            q=malicious,
            _=api_key,
            local_engine=mock_local_engine,
        )
        call_args = mock_local_engine.search.call_args
        passed_q = call_args.args[0] if call_args.args else call_args.kwargs.get("query")
        assert passed_q == malicious

    @pytest.mark.asyncio
    async def test_search_global_sql_injection_safely_passed(
        self,
        mock_request: MagicMock,
        mock_global_engine: MagicMock,
        api_key: str,
    ) -> None:
        """SQL injection payload (' OR '1'='1) on /search/global passed unchanged."""
        from api.endpoints.content.search import search_global

        malicious = SQL_INJECTION_PAYLOADS[1]  # "' OR '1'='1"
        await search_global(
            request=mock_request,
            q=malicious,
            community_level=0,
            _=api_key,
            global_engine=mock_global_engine,
        )
        call_args = mock_global_engine.search.call_args
        passed_q = call_args.args[0] if call_args.args else call_args.kwargs.get("query")
        assert passed_q == malicious


# ── Behavior verification ─────────────────────────────────────────────


class TestSearchShortcutsBehavior:
    """Verify shortcut endpoints inject correct metadata into SearchResponse."""

    @pytest.mark.asyncio
    async def test_search_local_returns_search_type_local(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        api_key: str,
    ) -> None:
        """/search/local response search_type MUST be "local"."""
        from api.endpoints.content.search import search_local

        result = await search_local(
            request=mock_request,
            q="华为",
            _=api_key,
            local_engine=mock_local_engine,
        )
        assert result.data.search_type == "local"

    @pytest.mark.asyncio
    async def test_search_global_returns_search_type_global(
        self,
        mock_request: MagicMock,
        mock_global_engine: MagicMock,
        api_key: str,
    ) -> None:
        """/search/global response search_type MUST be "global"."""
        from api.endpoints.content.search import search_global

        result = await search_global(
            request=mock_request,
            q="OpenAI",
            community_level=0,
            _=api_key,
            global_engine=mock_global_engine,
        )
        assert result.data.search_type == "global"

    @pytest.mark.asyncio
    async def test_search_shortcut_metadata_injection(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        api_key: str,
    ) -> None:
        """_execute_explicit_search injects the 4 standard metadata fields.

        Covers L240-243 of search.py:
        - output_mode=CONTEXT
        - enrich_entities=False
        - intent=OPEN
        - intent_confidence=1.0
        """
        from api.endpoints.content.search import search_local

        result = await search_local(
            request=mock_request,
            q="华为",
            _=api_key,
            local_engine=mock_local_engine,
        )
        assert result.data.metadata["output_mode"] == "CONTEXT"
        assert result.data.metadata["enrich_entities"] is False
        assert result.data.metadata["intent"] == "OPEN"
        assert result.data.metadata["intent_confidence"] == 1.0
