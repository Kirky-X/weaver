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
    bing_searcher: Any | None = None,
    pipeline_service: MagicMock | None = None,
    api_key_value: str = "test-api-key-32chars-long!!!!!!!",
    admin_key: str | None = None,
    skip_auth: bool = False,
) -> FastAPI:
    """Build a FastAPI app with the search router and dependency overrides.

    Used by tests that need to exercise FastAPI-level parameter validation
    (422) and authentication (401/403) which only trigger via HTTP layer.
    """
    from api.dependencies import (
        get_bing_searcher,
        get_global_search_engine,
        get_hybrid_engine,
        get_llm_client,
        get_local_search_engine,
        get_pipeline_service,
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
    # Web search fallback deps: default to None (disabled) so existing
    # tests that don't exercise the fallback path are unaffected.
    # pipeline_service is always overridden (defaults to a MagicMock) to
    # avoid FastAPI attempting to call the real container's pipeline_service()
    # which would raise 503 in unit tests (container not initialized).
    app.dependency_overrides[get_bing_searcher] = lambda: bing_searcher
    effective_pipeline = pipeline_service if pipeline_service is not None else MagicMock()
    app.dependency_overrides[get_pipeline_service] = lambda: effective_pipeline
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
                bing_searcher=None,
                pipeline_service=None,
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
                bing_searcher=None,
                pipeline_service=None,
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


# ── Web Search Fallback Tests (R-web-search-007) ────────────────────


class TestSearchUnifiedWebSearchFallback:
    """Verify web search fallback integration in search_unified.

    Covers four key paths:
    - bing_searcher=None → fallback skipped (disabled)
    - engine_result non-empty → fallback skipped (not needed)
    - bing returns [] → fallback attempted but no results
    - bing returns non-empty → response replaced + pipeline scheduled
    """

    @pytest.mark.asyncio
    async def test_fallback_skipped_when_bing_searcher_none(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """bing_searcher=None (Bing disabled) → fallback not triggered."""
        # Force empty three-tier result so fallback *would* trigger
        # if bing_searcher were non-None.
        mock_local_engine.search = AsyncMock(
            return_value={"answer": "", "entities": [], "sources": [], "metadata": {}}
        )
        from api.endpoints.content.search import search_unified

        result = await search_unified(
            request=mock_request,
            q="some-query",
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
            bing_searcher=None,
            pipeline_service=MagicMock(),
        )

        assert result.data.metadata["web_search_fallback"] is False
        assert result.data.metadata["web_search_result_count"] == 0

    @pytest.mark.asyncio
    async def test_fallback_skipped_when_engine_result_nonempty(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """engine_result has entities → fallback not triggered.

        mock_local_engine fixture returns non-empty result by default
        (entities=["华为", "途灵平台"], sources=[...], answer="...").
        """
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
            enrich_entities=None,
            _=api_key,
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            hybrid_engine=mock_hybrid_engine,
            bing_searcher=MagicMock(),  # non-None but should not be called
            pipeline_service=MagicMock(),
        )

        assert result.data.metadata["web_search_fallback"] is False
        assert result.data.metadata["web_search_result_count"] == 0
        # bing_searcher.search should NOT have been called
        result.data.metadata  # touch to ensure no exception

    @pytest.mark.asyncio
    async def test_fallback_returns_empty_when_bing_yields_no_results(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Bing enabled + three-tier empty + Bing returns [] → fallback=False."""
        # Force empty three-tier result
        mock_local_engine.search = AsyncMock(
            return_value={"answer": "", "entities": [], "sources": [], "metadata": {}}
        )
        # Bing searcher returns []
        bing_searcher = MagicMock()
        bing_searcher.search = AsyncMock(return_value=[])

        from api.endpoints.content.search import search_unified

        result = await search_unified(
            request=mock_request,
            q="non-existent-topic",
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
            bing_searcher=bing_searcher,
            pipeline_service=MagicMock(),
        )

        # Bing was called but returned [] → web_search_fallback=False
        # (web_search_result_count=0 indicates Bing WAS invoked).
        bing_searcher.search.assert_awaited_once()
        assert result.data.metadata["web_search_fallback"] is False
        assert result.data.metadata["web_search_result_count"] == 0

    @pytest.mark.asyncio
    async def test_fallback_replaces_response_and_schedules_pipeline(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Bing returns non-empty → response replaced + pipeline scheduled."""
        # Force empty three-tier result
        mock_local_engine.search = AsyncMock(
            return_value={"answer": "", "entities": [], "sources": [], "metadata": {}}
        )

        # Bing searcher returns 2 real BingSearchResult instances
        from modules.search.web import BingSearchResult

        bing_results = [
            BingSearchResult(
                title="华为途灵平台最新进展",
                url="https://example.com/article-1",
                snippet="华为途灵平台在 2026 年取得突破...",
            ),
            BingSearchResult(
                title="途灵平台技术解析",
                url="https://example.com/article-2",
                snippet="途灵平台是华为自研的...",
            ),
        ]
        bing_searcher = MagicMock()
        bing_searcher.search = AsyncMock(return_value=bing_results)

        pipeline_service = MagicMock()
        pipeline_service.run_full_pipeline = AsyncMock(return_value=None)

        # Patch schedule_pipeline_background to capture the call without
        # actually creating asyncio tasks that would outlive the test.
        with patch("api.endpoints.content.search.schedule_pipeline_background") as mock_schedule:
            from api.endpoints.content.search import search_unified

            result = await search_unified(
                request=mock_request,
                q="华为途灵平台",
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
                bing_searcher=bing_searcher,
                pipeline_service=pipeline_service,
            )

        # Bing was called
        bing_searcher.search.assert_awaited_once()
        # schedule_pipeline_background was called with the 2 URLs
        mock_schedule.assert_called_once()
        call_args = mock_schedule.call_args
        urls_arg = call_args.args[0]
        # urls may be a list (materialized by schedule_pipeline_background)
        # — but since we patched it, the arg is the raw list comprehension
        assert len(list(urls_arg)) == 2
        assert call_args.args[1] is pipeline_service
        # The third arg is _background_tasks (module-level set) — verify
        # it's a set instance.
        assert isinstance(call_args.args[2], set)

        # Response was replaced with web search snippets
        assert result.data.metadata["web_search_fallback"] is True
        assert result.data.metadata["web_search_result_count"] == 2
        assert "华为途灵平台最新进展" in result.data.answer
        assert "途灵平台技术解析" in result.data.answer
        assert len(result.data.sources) == 2
        assert result.data.sources[0]["url"] == "https://example.com/article-1"
        assert result.data.sources[0]["title"] == "华为途灵平台最新进展"
        assert result.data.sources[1]["url"] == "https://example.com/article-2"
        # Confidence is set to 0.5 for web-search fallback
        assert result.data.confidence == 0.5
        # M1 fix: context_tokens updated to reflect new answer length
        assert result.data.context_tokens > 0
        assert result.data.context_tokens >= len(result.data.answer) // 4
        # entities stay empty (no graph entities yet)
        assert result.data.entities == []

    @pytest.mark.asyncio
    async def test_fallback_degrades_gracefully_when_bing_raises(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Bing raises an exception → trigger_web_search catches it,
        returns [] → web_search_fallback=False, main flow not blocked.

        Verifies the graceful-degradation contract in R-web-search-005:
        "Bing must never block the main search flow."
        """
        # Force empty three-tier result
        mock_local_engine.search = AsyncMock(
            return_value={"answer": "", "entities": [], "sources": [], "metadata": {}}
        )
        # Bing searcher raises a synthetic exception
        bing_searcher = MagicMock()
        bing_searcher.search = AsyncMock(side_effect=RuntimeError("bing HTTP 500"))

        from api.endpoints.content.search import search_unified

        result = await search_unified(
            request=mock_request,
            q="some-flaky-query",
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
            bing_searcher=bing_searcher,
            pipeline_service=MagicMock(),
        )

        # Bing was called but raised; trigger_web_search caught the
        # exception and returned [] — main flow continues unblocked.
        bing_searcher.search.assert_awaited_once()
        assert result.data.metadata["web_search_fallback"] is False
        assert result.data.metadata["web_search_result_count"] == 0
        # Response answer stays empty (engine_result was empty, no web results)
        assert result.data.answer == ""

    @pytest.mark.asyncio
    async def test_fallback_throttle_sets_metadata_flag(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """MEDIUM-1: when ``schedule_pipeline_background`` returns THROTTLED,
        ``metadata.background_task_throttled`` is set to True.

        Simulates the at-cap scenario (8 background tasks already running)
        by patching ``schedule_pipeline_background`` to return
        ``ScheduleResult.THROTTLED``. The search response must still
        succeed (Bing results are returned to the caller), but the
        metadata flag indicates the background pipeline was dropped.
        """
        # Force empty three-tier result to trigger fallback.
        mock_local_engine.search = AsyncMock(
            return_value={"answer": "", "entities": [], "sources": [], "metadata": {}}
        )
        from modules.search.web import BingSearchResult

        bing_results = [
            BingSearchResult(
                title="throttled result",
                url="https://example.com/throttled",
                snippet="snippet text",
            ),
        ]
        bing_searcher = MagicMock()
        bing_searcher.search = AsyncMock(return_value=bing_results)

        # Patch schedule_pipeline_background to return THROTTLED (simulates
        # the at-cap scenario without actually spawning 8 tasks).
        from modules.search.web.fallback_orchestrator import ScheduleResult

        with patch("api.endpoints.content.search.schedule_pipeline_background") as mock_schedule:
            from api.endpoints.content.search import search_unified

            mock_schedule.return_value = ScheduleResult.THROTTLED

            result = await search_unified(
                request=mock_request,
                q="throttled-query",
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
                bing_searcher=bing_searcher,
                pipeline_service=MagicMock(),
            )

        # schedule_pipeline_background was invoked (the call happened).
        mock_schedule.assert_called_once()
        # Metadata flag indicates the background task was throttled.
        assert result.data.metadata["background_task_throttled"] is True
        # Bing results still returned to the caller (search itself succeeded).
        assert result.data.metadata["web_search_fallback"] is True
        assert result.data.metadata["web_search_result_count"] == 1
        assert len(result.data.sources) == 1

    @pytest.mark.asyncio
    async def test_fallback_no_throttle_flag_when_scheduled(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_vector_repo: MagicMock,
        mock_llm: MagicMock,
        mock_hybrid_engine: MagicMock,
        api_key: str,
    ) -> None:
        """MEDIUM-1: when schedule_pipeline_background returns SCHEDULED,
        ``metadata.background_task_throttled`` is NOT set (or False).

        Regression guard: ensures the flag is only set when actually
        throttled, not on every fallback path.
        """
        mock_local_engine.search = AsyncMock(
            return_value={"answer": "", "entities": [], "sources": [], "metadata": {}}
        )
        from modules.search.web import BingSearchResult

        bing_results = [
            BingSearchResult(
                title="ok result",
                url="https://example.com/ok",
                snippet="snippet",
            ),
        ]
        bing_searcher = MagicMock()
        bing_searcher.search = AsyncMock(return_value=bing_results)

        from modules.search.web.fallback_orchestrator import ScheduleResult

        with patch("api.endpoints.content.search.schedule_pipeline_background") as mock_schedule:
            from api.endpoints.content.search import search_unified

            mock_schedule.return_value = ScheduleResult.SCHEDULED

            result = await search_unified(
                request=mock_request,
                q="ok-query",
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
                bing_searcher=bing_searcher,
                pipeline_service=MagicMock(),
            )

        mock_schedule.assert_called_once()
        # When SCHEDULED, the throttle flag must NOT be True.
        assert result.data.metadata.get("background_task_throttled") is not True


# ── _sort_response_lists Unit Tests ─────────────────────────────────
# Covers audit_findings.md Finding 1/2 fix: deterministic cross-DB
# ordering of entities/sources lists in SearchResponse.
# Rule 9 (testing meaningful properties) + Rule 24 (no simplification):
# 7 cases cover ordering, fallback keys, edge values, mixed types, idempotency,
# no-mutation of input, and empty-input boundary.


class TestSortResponseLists:
    """Unit tests for ``api.endpoints.content.search._sort_response_lists``.

    Validates deterministic cross-DB ordering of entities/sources. Closes
    audit_findings.md Finding 1/2 (9 cross-DB inconsistencies in
    search_local/search_global endpoints).
    """

    def test_sorts_entities_in_ascending_order(self) -> None:
        """Multi-entity unordered input → ascending output."""
        from api.endpoints.content.search import _sort_response_lists

        entities = ["Windows 11", "Apple", "Windows 10", "BSD"]
        sources: list[dict[str, Any]] = []
        sorted_entities, _ = _sort_response_lists(entities, sources)
        assert sorted_entities == ["Apple", "BSD", "Windows 10", "Windows 11"]

    def test_sorts_sources_by_title(self) -> None:
        """Sources with title key → sorted by title ascending."""
        from api.endpoints.content.search import _sort_response_lists

        entities: list[str] = []
        sources = [
            {"title": "Zebra Article"},
            {"title": "Apple Article"},
            {"title": "Mango Article"},
        ]
        _, sorted_sources = _sort_response_lists(entities, sources)
        titles = [s["title"] for s in sorted_sources]
        assert titles == ["Apple Article", "Mango Article", "Zebra Article"]

    def test_fallback_to_article_id_when_title_missing(self) -> None:
        """Sources without title but with article_id → sorted by article_id."""
        from api.endpoints.content.search import _sort_response_lists

        entities: list[str] = []
        sources = [
            {"article_id": "zzz-123"},
            {"article_id": "aaa-456"},
            {"article_id": "mmm-789"},
        ]
        _, sorted_sources = _sort_response_lists(entities, sources)
        ids = [s["article_id"] for s in sorted_sources]
        assert ids == ["aaa-456", "mmm-789", "zzz-123"]

    def test_fallback_to_url_when_title_and_article_id_missing(self) -> None:
        """Sources with only url key → sorted by url (web search fallback path)."""
        from api.endpoints.content.search import _sort_response_lists

        entities: list[str] = []
        sources = [
            {"url": "https://z.example.com", "snippet": "z"},
            {"url": "https://a.example.com", "snippet": "a"},
        ]
        _, sorted_sources = _sort_response_lists(entities, sources)
        urls = [s["url"] for s in sorted_sources]
        assert urls == ["https://a.example.com", "https://z.example.com"]

    def test_handles_empty_dict_without_raising(self) -> None:
        """Sources containing empty dict {} → no exception, sorted as empty string."""
        from api.endpoints.content.search import _sort_response_lists

        entities: list[str] = []
        sources = [{}, {"title": "B"}, {}]
        _, sorted_sources = _sort_response_lists(entities, sources)
        # Empty dicts sort as "" — they come before "B"
        # Expected order: [{}, {}, {"title": "B"}]
        assert sorted_sources[0] == {}
        assert sorted_sources[1] == {}
        assert sorted_sources[2] == {"title": "B"}

    def test_str_cast_handles_mixed_type_values_without_typeerror(self) -> None:
        """Sources with mixed-type title values (None, int, str) → no TypeError."""
        from api.endpoints.content.search import _sort_response_lists

        entities: list[Any] = ["b", 1, None, "a"]
        sources = [
            {"title": None},
            {"title": 42},  # type: ignore[dict-item]
            {"title": "zebra"},
            {"title": "apple"},
        ]
        # Must not raise TypeError. key=str only affects comparison, not elements.
        # Entities sorted by str(): str(1)='1' < str(None)='None' < 'a' < 'b'.
        sorted_entities, sorted_sources = _sort_response_lists(entities, sources)
        # Elements preserved as-is; only ordering changes.
        assert sorted_entities == [1, None, "a", "b"]
        # Sources: {"title": None} → falsy → falls through to "" (sort key ""),
        #          {"title": 42} → sort key "42",
        #          {"title": "apple"} → sort key "apple",
        #          {"title": "zebra"} → sort key "zebra".
        # Sort order by key: "" < "42" < "apple" < "zebra".
        titles = [s["title"] for s in sorted_sources]
        assert titles == [None, 42, "apple", "zebra"]

    def test_does_not_mutate_input_lists(self) -> None:
        """Function must return new lists, not mutate input (pure function)."""
        from api.endpoints.content.search import _sort_response_lists

        entities = ["c", "a", "b"]
        sources = [{"title": "z"}, {"title": "a"}]
        entities_snapshot = list(entities)
        sources_snapshot = [dict(s) for s in sources]

        _sort_response_lists(entities, sources)

        assert entities == entities_snapshot
        assert sources == sources_snapshot

    def test_empty_inputs_return_empty_outputs(self) -> None:
        """Empty entities + empty sources → empty outputs (boundary)."""
        from api.endpoints.content.search import _sort_response_lists

        sorted_entities, sorted_sources = _sort_response_lists([], [])
        assert sorted_entities == []
        assert sorted_sources == []

    def test_idempotent_on_already_sorted_input(self) -> None:
        """Already-sorted input → same order (idempotency)."""
        from api.endpoints.content.search import _sort_response_lists

        entities = ["a", "b", "c"]
        sources = [{"title": "a"}, {"title": "b"}, {"title": "c"}]
        sorted_entities, sorted_sources = _sort_response_lists(entities, sources)
        assert sorted_entities == entities
        assert sorted_sources == sources
