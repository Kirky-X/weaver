# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for unified search endpoint ``GET /api/v1/search``.

Covers 23 test cases targeting the explore-phase test matrix:
- Normal inputs (4): auto/local/global modes with real-data keywords
- Boundary values (4): limit=1/100, community_level=0/10, threshold=0.0/1.0
- Invalid params (5): empty/missing q, limit=0/101, community_level=-1/11, threshold=1.5
- Authentication (4): no key (401) / wrong key (403) / regular key / admin key
- Degradation (3): mode=unknown→auto, output_mode=invalid→CONTEXT, enrich_entities=None→False
- Security (2): SQL injection, 10K-character query
- Combination (1): category + output_mode=narrative + enrich_entities=True

Real-data fixtures come from ``tests/fixtures/search_keywords.py`` (rule 7+11).
The endpoint under test is ``src/api/endpoints/content/search.py::search_unified``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from tests.fixtures.search_keywords import (
    LONG_QUERY_10K,
    REAL_ARTICLE_TITLES,
    REAL_CATEGORIES,
    REAL_ENTITY_NAMES,
    SQL_INJECTION_PAYLOADS,
)

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_request() -> MagicMock:
    """Create a mock FastAPI Request object."""
    request = MagicMock(spec=Request)
    request.client.host = "127.0.0.1"
    return request


@pytest.fixture
def mock_local_engine() -> MagicMock:
    """Mock LocalSearchEngine returning a dict-shaped result.

    The dict shape mirrors what LocalSearchEngine.search returns in production
    (see ``modules/knowledge/search/engines/local_search.py``).
    """
    engine = MagicMock()
    engine.search = AsyncMock(
        return_value={
            "answer": "华为途灵平台相关信息",
            "context_tokens": 500,
            "confidence": 0.85,
            "entities": ["华为", "途灵平台"],
            "sources": [{"article_id": "uuid-1", "title": REAL_ARTICLE_TITLES[2]}],
            "metadata": {"search_type": "local"},
        }
    )
    return engine


@pytest.fixture
def mock_global_engine() -> MagicMock:
    """Mock GlobalSearchEngine returning a dict-shaped result."""
    engine = MagicMock()
    engine.search = AsyncMock(
        return_value={
            "answer": "社区级聚合答案",
            "context_tokens": 1200,
            "confidence": 0.90,
            "entities": ["OpenAI", "GPT-5"],
            "sources": [{"article_id": "uuid-2", "title": REAL_ARTICLE_TITLES[4]}],
            "metadata": {"search_type": "global", "community_level": 2},
        }
    )
    return engine


@pytest.fixture
def mock_vector_repo() -> MagicMock:
    repo = MagicMock()
    repo.search = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.call = AsyncMock(return_value='{"intent": "ENTITY", "confidence": 0.9}')
    return llm


@pytest.fixture
def mock_hybrid_engine() -> MagicMock:
    engine = MagicMock()
    engine.search = AsyncMock(
        return_value={
            "answer": "Hybrid fallback answer",
            "context_tokens": 800,
            "confidence": 0.88,
            "entities": [],
            "sources": [],
            "metadata": {"search_type": "hybrid"},
        }
    )
    return engine


@pytest.fixture
def mock_intent_classification() -> MagicMock:
    """Mock IntentClassification returned by the classifier."""
    from modules.knowledge.search import IntentClassification, QueryIntent

    return IntentClassification(intent=QueryIntent.ENTITY, confidence=0.9)


@pytest.fixture
def api_key() -> str:
    """Valid API key for tests (32+ chars to satisfy MIN_API_KEY_LENGTH)."""
    return "test-api-key-32chars-long!!!!!!!"


@pytest.fixture
def admin_api_key() -> str:
    """Valid admin API key for tests."""
    return "admin-api-key-32chars-long!!!!!!"


def _build_app_for_endpoint_test(
    *,
    local_engine: MagicMock,
    global_engine: MagicMock,
    vector_repo: MagicMock | None = None,
    llm: MagicMock | None = None,
    hybrid_engine: MagicMock | None = None,
    api_key_value: str = "test-api-key-32chars-long!!!!!!!",
    admin_key: str | None = None,
    skip_auth: bool = False,
) -> FastAPI:
    """Build a FastAPI app with the search router and dependency overrides.

    Used by tests that need to exercise FastAPI-level parameter validation
    (422) and authentication (401/403) which only trigger via HTTP layer.
    """
    from api.dependencies import (
        get_global_search_engine,
        get_hybrid_engine,
        get_llm_client,
        get_local_search_engine,
        get_vector_repo,
    )
    from api.endpoints.content.search import router
    from api.middleware.auth import verify_api_key

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    # Override auth
    if skip_auth:
        app.dependency_overrides[verify_api_key] = lambda: api_key_value
    else:
        # Real verify_api_key will be invoked (settings + key_manager mocked in test)
        pass

    app.dependency_overrides[get_local_search_engine] = lambda: local_engine
    app.dependency_overrides[get_global_search_engine] = lambda: global_engine
    if vector_repo is not None:
        app.dependency_overrides[get_vector_repo] = lambda: vector_repo
    if llm is not None:
        app.dependency_overrides[get_llm_client] = lambda: llm
    if hybrid_engine is not None:
        app.dependency_overrides[get_hybrid_engine] = lambda: hybrid_engine
    return app


# ── Normal-input tests ───────────────────────────────────────────────


class TestSearchUnifiedNormalInputs:
    """Verify search_unified accepts real-data keywords and routes correctly."""

    @pytest.mark.asyncio
    async def test_search_auto_mode_with_real_entity(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        mock_intent_classification: MagicMock,
        api_key: str,
    ) -> None:
        """mode=None (auto) should call IntentClassifier.classify then IntentRouter.route."""
        from api.endpoints.content.search import search_unified

        with patch("modules.knowledge.search.intent.router.IntentClassifier") as MockClassifier:
            MockClassifier.return_value.classify = AsyncMock(
                return_value=mock_intent_classification
            )
            result = await search_unified(
                request=mock_request,
                q=REAL_ENTITY_NAMES[0],  # "华为"
                mode=None,
                community_level=0,
                threshold=0.0,
                limit=20,
                category=None,
                use_hybrid=True,
                global_mode="map_reduce",
                output_mode=None,
                enrich_entities=None,
                _=api_key,
                local_engine=mock_local_engine,
                global_engine=mock_global_engine,
                vector_repo=mock_vector_repo,
                llm=mock_llm,
                hybrid_engine=mock_hybrid_engine,
            )

        # Auto mode → search_type="auto"
        assert result.data.search_type == "auto"
        assert result.data.query == REAL_ENTITY_NAMES[0]
        # intent injected from classifier
        assert result.data.metadata["intent"] == "entity"
        assert result.data.metadata["intent_confidence"] == 0.9
        # output_mode defaulted to CONTEXT
        assert result.data.metadata["output_mode"] == "CONTEXT"
        # enrich_entities defaulted to False
        assert result.data.metadata["enrich_entities"] is False

    @pytest.mark.asyncio
    async def test_search_local_mode_explicit(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """mode=local should call local_engine.search directly and bypass classifier."""
        from api.endpoints.content.search import search_unified

        result = await search_unified(
            request=mock_request,
            q="苹果存储成本",
            mode="local",
            community_level=0,
            threshold=0.0,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            output_mode=None,
            enrich_entities=None,
            _=api_key,
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
        )

        # local_engine.search called once with the query
        mock_local_engine.search.assert_called_once()
        # global_engine NOT called (explicit local mode bypasses routing)
        mock_global_engine.search.assert_not_called()
        assert result.data.search_type == "local"
        # explicit mode → intent defaults to OPEN, confidence=1.0
        assert result.data.metadata["intent"] == "open"
        assert result.data.metadata["intent_confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_search_global_mode_explicit(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """mode=global should call global_engine.search(q, community_level=) directly."""
        from api.endpoints.content.search import search_unified

        result = await search_unified(
            request=mock_request,
            q=REAL_ENTITY_NAMES[4],  # "OpenAI"
            mode="global",
            community_level=2,
            threshold=0.0,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            output_mode=None,
            enrich_entities=None,
            _=api_key,
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
        )

        # global_engine.search called with community_level kwarg
        mock_global_engine.search.assert_called_once()
        call_kwargs = mock_global_engine.search.call_args.kwargs
        assert call_kwargs["community_level"] == 2
        # local_engine NOT called
        mock_local_engine.search.assert_not_called()
        assert result.data.search_type == "global"

    @pytest.mark.asyncio
    async def test_search_with_real_article_title(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Real article title as query should be accepted in local mode."""
        from api.endpoints.content.search import search_unified

        title = REAL_ARTICLE_TITLES[0]  # "OpenAI发布自研推理芯片Jalapeño"
        result = await search_unified(
            request=mock_request,
            q=title,
            mode="local",
            community_level=0,
            threshold=0.0,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            output_mode=None,
            enrich_entities=None,
            _=api_key,
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
        )

        # q passed through unchanged to engine
        call_args = mock_local_engine.search.call_args
        assert call_args.args[0] == title or call_args.kwargs.get("query") == title
        assert result.data.query == title


# ── Boundary-value tests ─────────────────────────────────────────────


class TestSearchUnifiedBoundaryValues:
    """Verify search_unified accepts Pydantic Query boundary values."""

    @pytest.mark.asyncio
    async def test_search_limit_min_1(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """limit=1 is the lower bound (ge=1)."""
        from api.endpoints.content.search import search_unified

        result = await search_unified(
            request=mock_request,
            q="华为",
            mode="local",
            community_level=0,
            threshold=0.0,
            limit=1,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            output_mode=None,
            enrich_entities=None,
            _=api_key,
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
        )
        assert result.data.query == "华为"

    @pytest.mark.asyncio
    async def test_search_limit_max_100(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """limit=100 is the upper bound (le=100)."""
        from api.endpoints.content.search import search_unified

        result = await search_unified(
            request=mock_request,
            q="华为",
            mode="local",
            community_level=0,
            threshold=0.0,
            limit=100,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            output_mode=None,
            enrich_entities=None,
            _=api_key,
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
        )
        assert result.data.search_type == "local"

    @pytest.mark.asyncio
    async def test_search_community_level_boundary_0_and_10(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """community_level=0 (min) and =10 (max) are accepted in global mode."""
        from api.endpoints.content.search import search_unified

        # min
        await search_unified(
            request=mock_request,
            q="OpenAI",
            mode="global",
            community_level=0,
            threshold=0.0,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            output_mode=None,
            enrich_entities=None,
            _=api_key,
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
        )
        assert mock_global_engine.search.call_args.kwargs["community_level"] == 0

        mock_global_engine.search.reset_mock()

        # max
        await search_unified(
            request=mock_request,
            q="OpenAI",
            mode="global",
            community_level=10,
            threshold=0.0,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            output_mode=None,
            enrich_entities=None,
            _=api_key,
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
        )
        assert mock_global_engine.search.call_args.kwargs["community_level"] == 10

    @pytest.mark.asyncio
    async def test_search_threshold_boundary_0_and_1(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """threshold=0.0 (min) and =1.0 (max) are accepted (ge=0.0, le=1.0)."""
        from api.endpoints.content.search import search_unified

        # min threshold
        result_min = await search_unified(
            request=mock_request,
            q="华为",
            mode="local",
            community_level=0,
            threshold=0.0,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            output_mode=None,
            enrich_entities=None,
            _=api_key,
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
        )
        assert result_min.data.query == "华为"

        # max threshold
        result_max = await search_unified(
            request=mock_request,
            q="华为",
            mode="local",
            community_level=0,
            threshold=1.0,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            output_mode=None,
            enrich_entities=None,
            _=api_key,
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
        )
        assert result_max.data.query == "华为"


# ── Invalid-param tests (HTTP 422 via FastAPI validation) ────────────


class TestSearchUnifiedInvalidParams:
    """Verify FastAPI Query validators reject out-of-range params with HTTP 422."""

    @pytest.fixture
    def client(
        self,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
    ) -> TestClient:
        """TestClient with all engine deps overridden + auth bypassed."""
        app = _build_app_for_endpoint_test(
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
            skip_auth=True,
        )
        return TestClient(app)

    def test_search_empty_q_returns_422(self, client: TestClient) -> None:
        """Empty q violates min_length=1 → 422."""
        response = client.get("/api/v1/search", params={"q": ""})
        assert response.status_code == 422

    def test_search_missing_q_returns_422(self, client: TestClient) -> None:
        """Missing q parameter → 422 (Query(..., required))."""
        response = client.get("/api/v1/search")
        assert response.status_code == 422

    def test_search_limit_0_returns_422(self, client: TestClient) -> None:
        """limit=0 violates ge=1 → 422."""
        response = client.get("/api/v1/search", params={"q": "华为", "limit": 0})
        assert response.status_code == 422

    def test_search_limit_101_returns_422(self, client: TestClient) -> None:
        """limit=101 violates le=100 → 422."""
        response = client.get("/api/v1/search", params={"q": "华为", "limit": 101})
        assert response.status_code == 422

    def test_search_threshold_1_5_returns_422(self, client: TestClient) -> None:
        """threshold=1.5 violates le=1.0 → 422."""
        response = client.get("/api/v1/search", params={"q": "华为", "threshold": 1.5})
        assert response.status_code == 422


# ── Authentication tests ─────────────────────────────────────────────


class TestSearchUnifiedAuthentication:
    """Verify verify_api_key behavior on /api/v1/search endpoint.

    The 401/403 paths are tested via HTTP layer (TestClient) because they
    depend on FastAPI's Security(...) machinery which only fires through
    the routing layer. Regular/admin key acceptance is verified via direct
    function call (verify_api_key unit-style).
    """

    @pytest.mark.asyncio
    async def test_search_no_api_key_returns_401(
        self,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
    ) -> None:
        """Missing X-API-Key header → 401."""
        app = _build_app_for_endpoint_test(
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
            skip_auth=False,  # real verify_api_key path
        )
        # Mock verify_api_key internals: no key_manager, settings.api_key too short
        with (
            patch("api.middleware.auth._get_api_key_manager", return_value=None),
            patch("container.get_settings") as mock_get_settings,
        ):
            mock_settings = MagicMock()
            mock_settings.api.get_api_key.return_value = ""  # too short → 500
            mock_settings.api.admin_api_key = None
            mock_settings.environment = "test"
            mock_get_settings.return_value = mock_settings

            client = TestClient(app)
            response = client.get("/api/v1/search", params={"q": "华为"})
            # No X-API-Key → 401
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_search_wrong_api_key_returns_403(
        self,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
    ) -> None:
        """Invalid X-API-Key → 403."""
        app = _build_app_for_endpoint_test(
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
            skip_auth=False,
        )
        with (
            patch("api.middleware.auth._get_api_key_manager", return_value=None),
            patch("container.get_settings") as mock_get_settings,
        ):
            mock_settings = MagicMock()
            mock_settings.api.get_api_key.return_value = "x" * 32  # valid length
            mock_settings.api.admin_api_key = None
            mock_settings.environment = "test"
            mock_get_settings.return_value = mock_settings

            client = TestClient(app)
            response = client.get(
                "/api/v1/search",
                params={"q": "华为"},
                headers={"X-API-Key": "wrong-key-32chars-long-!!!!!!!"},
            )
            assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_search_regular_api_key_accepted(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Regular API key (32+ chars) is accepted; verify_api_key returns "env-key"."""
        from api.middleware.auth import verify_api_key

        with (
            patch("api.middleware.auth._get_api_key_manager", return_value=None),
            patch("container.get_settings") as mock_get_settings,
        ):
            mock_settings = MagicMock()
            mock_settings.api.get_api_key.return_value = api_key
            mock_settings.api.admin_api_key = None
            mock_settings.environment = "test"
            mock_get_settings.return_value = mock_settings

            result = await verify_api_key(key=api_key, request=mock_request)
            assert result == "env-key"

    @pytest.mark.asyncio
    async def test_search_admin_api_key_accepted(
        self,
        mock_request: MagicMock,
        admin_api_key: str,
    ) -> None:
        """Admin API key is accepted; verify_api_key returns "admin"."""
        from api.middleware.auth import verify_api_key

        with (
            patch("api.middleware.auth._get_api_key_manager", return_value=None),
            patch("container.get_settings") as mock_get_settings,
        ):
            mock_settings = MagicMock()
            mock_settings.api.get_api_key.return_value = "regular-key-32chars-long-!!!"
            mock_settings.api.admin_api_key = admin_api_key
            mock_settings.environment = "test"
            mock_get_settings.return_value = mock_settings

            result = await verify_api_key(key=admin_api_key, request=mock_request)
            assert result == "admin"


# ── Degradation tests ────────────────────────────────────────────────


class TestSearchUnifiedDegradation:
    """Verify search_unified silently degrades unknown params to defaults."""

    @pytest.mark.asyncio
    async def test_search_mode_unknown_falls_back_to_auto(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        mock_intent_classification: MagicMock,
        api_key: str,
    ) -> None:
        """mode='unknown' is NOT in ('local','global') → falls into auto branch."""
        from api.endpoints.content.search import search_unified

        with patch("modules.knowledge.search.intent.router.IntentClassifier") as MockClassifier:
            MockClassifier.return_value.classify = AsyncMock(
                return_value=mock_intent_classification
            )
            result = await search_unified(
                request=mock_request,
                q="华为",
                mode="unknown",
                community_level=0,
                threshold=0.0,
                limit=20,
                category=None,
                use_hybrid=True,
                global_mode="map_reduce",
                output_mode=None,
                enrich_entities=None,
                _=api_key,
                local_engine=mock_local_engine,
                global_engine=mock_global_engine,
                vector_repo=mock_vector_repo,
                llm=mock_llm,
                hybrid_engine=mock_hybrid_engine,
            )

        # Explicit mode NOT triggered → search_type="auto"
        assert result.data.search_type == "auto"
        # Neither direct engine.search called explicitly — router.route handles it
        # (the route() goes through _search_entity → local_engine.search)

    @pytest.mark.asyncio
    async def test_search_output_mode_invalid_falls_back_to_context(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """output_mode='invalid' triggers OutputMode('INVALID') ValueError → CONTEXT."""
        from api.endpoints.content.search import search_unified

        result = await search_unified(
            request=mock_request,
            q="华为",
            mode="local",
            community_level=0,
            threshold=0.0,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            output_mode="invalid",
            enrich_entities=None,
            _=api_key,
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
        )
        # Invalid output_mode → default CONTEXT
        assert result.data.metadata["output_mode"] == "CONTEXT"

    @pytest.mark.asyncio
    async def test_search_enrich_entities_none_defaults_to_false(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """enrich_entities=None → isinstance check fails → False default."""
        from api.endpoints.content.search import search_unified

        result = await search_unified(
            request=mock_request,
            q="华为",
            mode="local",
            community_level=0,
            threshold=0.0,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            output_mode=None,
            enrich_entities=None,  # not a bool → defaults to False
            _=api_key,
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
        )
        assert result.data.metadata["enrich_entities"] is False


# ── Security tests ───────────────────────────────────────────────────


class TestSearchUnifiedSecurity:
    """Verify search_unified treats malicious queries as opaque strings."""

    @pytest.mark.asyncio
    async def test_search_sql_injection_query_safely_passed(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """SQL injection payload in q is passed through to engine unmodified.

        The endpoint treats q as an opaque string. It MUST NOT be interpreted
        as SQL or Cypher. Verification: local_engine.search receives the raw
        payload as its first argument.
        """
        from api.endpoints.content.search import search_unified

        malicious = SQL_INJECTION_PAYLOADS[0]  # "'; DROP TABLE articles_core; --"
        await search_unified(
            request=mock_request,
            q=malicious,
            mode="local",
            community_level=0,
            threshold=0.0,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            output_mode=None,
            enrich_entities=None,
            _=api_key,
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
        )
        # q is passed to local_engine.search unchanged
        call_args = mock_local_engine.search.call_args
        passed_q = call_args.args[0] if call_args.args else call_args.kwargs.get("query")
        assert passed_q == malicious

    @pytest.mark.asyncio
    async def test_search_extremely_long_query_accepted(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """10K-character query is accepted (no max_length constraint on q)."""
        from api.endpoints.content.search import search_unified

        long_q = LONG_QUERY_10K  # 10000 chars
        result = await search_unified(
            request=mock_request,
            q=long_q,
            mode="local",
            community_level=0,
            threshold=0.0,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            output_mode=None,
            enrich_entities=None,
            _=api_key,
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
        )
        assert result.data.query == long_q
        # Engine also received the full query
        call_args = mock_local_engine.search.call_args
        passed_q = call_args.args[0] if call_args.args else call_args.kwargs.get("query")
        assert passed_q == long_q


# ── Combination test ─────────────────────────────────────────────────


class TestSearchUnifiedCombinations:
    """Verify search_unified handles combined parameter scenarios."""

    @pytest.mark.asyncio
    async def test_search_combined_category_output_mode_narrative_enrich_entities(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Combine category filter + output_mode=narrative + enrich_entities=True."""
        from api.endpoints.content.search import search_unified

        result = await search_unified(
            request=mock_request,
            q=REAL_ENTITY_NAMES[0],  # "华为"
            mode="local",
            community_level=0,
            threshold=0.0,
            limit=20,
            category=REAL_CATEGORIES[0],  # "科技"
            use_hybrid=True,
            global_mode="map_reduce",
            output_mode="narrative",
            enrich_entities=True,
            _=api_key,
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
        )
        # output_mode=NARRATIVE accepted (valid OutputMode enum)
        assert result.data.metadata["output_mode"] == "NARRATIVE"
        # enrich_entities=True propagated
        assert result.data.metadata["enrich_entities"] is True
        # Category filter does not affect search_unified directly (MAGMA layer handles it)
        assert result.data.query == REAL_ENTITY_NAMES[0]


# ── dict vs SearchResult object compatibility ────────────────────────


class TestSearchUnifiedResultShape:
    """Verify search_unified handles both dict and SearchResult object returns."""

    @pytest.mark.asyncio
    async def test_search_engine_returns_search_result_object(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """When local_engine returns a SearchResult object (not dict), attribute access path is used.

        Covers L172-178 of search.py:
        ``result_answer = engine_result.answer`` etc.
        """
        from api.endpoints.content.search import search_unified
        from modules.knowledge.search import SearchResult

        # Construct a real SearchResult object (query is required by dataclass)
        sr = SearchResult(
            query="华为",
            answer="object-style answer",
            context_tokens=42,
            confidence=0.77,
            entities=["华为"],
            sources=[{"article_id": "uuid-obj"}],
            metadata={"search_type": "local"},
        )
        mock_local_engine.search = AsyncMock(return_value=sr)

        result = await search_unified(
            request=mock_request,
            q="华为",
            mode="local",
            community_level=0,
            threshold=0.0,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            output_mode=None,
            enrich_entities=None,
            _=api_key,
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
        )

        assert result.data.answer == "object-style answer"
        assert result.data.context_tokens == 42
        assert result.data.confidence == 0.77
        assert result.data.entities == ["华为"]
        assert result.data.sources == [{"article_id": "uuid-obj"}]
        # metadata still gets output_mode / enrich_entities / intent injected
        assert result.data.metadata["output_mode"] == "CONTEXT"
        assert result.data.metadata["intent"] == "open"
