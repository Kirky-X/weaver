# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for HIGH-finding fixes in api/middleware and api/endpoints.

Covers:
- performance middleware records metrics when call_next raises
-: metric path uses the route template, not the raw URL path
-: HTTPLoggingMiddleware no longer buffers bodies when logging off
-: RequestContextMiddleware sanitizes X-Request-ID
-: HMAC middleware skipped when no usable secret is configured
- analytics briefings endpoint logs failures
- GlobalSearchEngine.get_drift_deps validates the LLM client
- graph get_entity no longer double-decodes path parameters
- LLM usage shared query forwards all filter parameters
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.middleware.performance import PerformanceMonitoringMiddleware, _metric_path

# ── +: performance middleware ───────────────────────────────


def _fake_request(
    path: str = "/articles/42", route_template: str | None = "/articles/{article_id}"
):
    request = MagicMock()
    scope: dict = {}
    if route_template is not None:
        scope["route"] = MagicMock(path=route_template)
    request.scope = scope
    request.url.path = path
    request.method = "GET"
    return request


class TestPerformanceMiddlewareErrorPath:
    @pytest.mark.asyncio
    async def test_metrics_recorded_when_call_next_raises(self):
        """errored requests still record timing + Prometheus data."""
        mw = PerformanceMonitoringMiddleware(app=MagicMock())
        request = _fake_request()

        async def boom(_request):
            raise RuntimeError("downstream failure")

        with patch("api.middleware.prometheus_metrics.record_http_request") as mock_record:
            with pytest.raises(RuntimeError, match="downstream failure"):
                await mw.dispatch(request, boom)
            mock_record.assert_called_once()
            kwargs = mock_record.call_args.kwargs
            assert kwargs["status"] == 500

    @pytest.mark.asyncio
    async def test_exception_is_reraised_unchanged(self):
        mw = PerformanceMonitoringMiddleware(app=MagicMock())
        request = _fake_request()
        sentinel = ValueError("original")

        async def boom(_request):
            raise sentinel

        with pytest.raises(ValueError) as exc_info:
            await mw.dispatch(request, boom)
        assert exc_info.value is sentinel


class TestMetricPath:
    def test_uses_route_template(self):
        """Dynamic IDs collapse into the route template."""
        request = _fake_request(path="/articles/9f8c-uuid", route_template="/articles/{article_id}")
        assert _metric_path(request) == "/articles/{article_id}"

    def test_unmatched_route_falls_back(self):
        request = _fake_request(route_template=None)
        assert _metric_path(request) == "unmatched"


# ──: HTTPLoggingMiddleware ──────────────────────────────────────────


class _BodySendingApp:
    """ASGI app that emits a response body in `chunks` pieces."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __call__(self, scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        for chunk in self._chunks:
            await send({"type": "http.response.body", "body": chunk})


async def _run_logging_middleware(mw, scope):
    messages: list[dict] = []

    async def send(message):
        messages.append(message)

    async def receive():  # pragma: no cover - unused
        return {"type": "http.request"}

    await mw(scope, receive, send)
    return messages


class TestHTTPLoggingBodyBuffering:
    @pytest.mark.asyncio
    async def test_body_size_counted_without_buffering(self):
        """Body_size stays accurate while nothing large is buffered."""
        from api.middleware.asgi import HTTPLoggingMiddleware

        big = b"x" * 100_000
        mw = HTTPLoggingMiddleware(app=_BodySendingApp([big, big]), log_response_body=False)
        with patch("api.middleware.asgi.log") as mock_log:
            await _run_logging_middleware(mw, {"type": "http", "headers": []})
            kwargs = mock_log.info.call_args.kwargs
            assert kwargs["body_size"] == 200_000

    @pytest.mark.asyncio
    async def test_body_capture_bounded_when_logging_enabled(self):
        """With logging on, only the preview window is buffered."""
        from api.middleware.asgi import _MAX_BODY_CAPTURE, HTTPLoggingMiddleware

        big = b"y" * 10_000
        mw = HTTPLoggingMiddleware(app=_BodySendingApp([big]), log_response_body=True)
        with patch("api.middleware.asgi.log") as mock_log:
            await _run_logging_middleware(mw, {"type": "http", "headers": []})
            kwargs = mock_log.debug.call_args.kwargs
            assert kwargs["body_size"] == 10_000
            # Preview stays within the declared window regardless of body size
            assert len(kwargs["body_preview"]) <= 503  # 500 chars + ellipsis


# ──: RequestContextMiddleware ────────────────────────────────────────


def _make_scope(request_id: bytes | None) -> dict:
    headers = []
    if request_id is not None:
        headers.append((b"x-request-id", request_id))
    return {"type": "http", "headers": headers}


class _EchoApp:
    def __init__(self) -> None:
        self.start_message: dict | None = None

    async def __call__(self, scope, receive, send):
        message = {"type": "http.response.start", "status": 200, "headers": []}
        self.start_message = message
        await send(message)
        await send({"type": "http.response.body", "body": b"ok"})


def _response_request_id(app: _EchoApp) -> str:
    headers = dict(app.start_message["headers"])
    return headers[b"X-Request-ID"].decode()


class TestRequestContextSanitization:
    @pytest.mark.asyncio
    async def test_valid_request_id_preserved(self):
        from api.middleware.request_context import RequestContextMiddleware

        app = _EchoApp()
        mw = RequestContextMiddleware(app=app)
        await mw(_make_scope(b"abc-123-XYZ"), AsyncMock(), AsyncMock())
        assert _response_request_id(app) == "abc-123-XYZ"

    @pytest.mark.asyncio
    async def test_crlf_injection_rejected(self):
        """CR/LF in X-Request-ID must not reach the response header."""
        from api.middleware.request_context import RequestContextMiddleware

        app = _EchoApp()
        mw = RequestContextMiddleware(app=app)
        await mw(_make_scope(b"evil\r\nX-Injected: 1"), AsyncMock(), AsyncMock())
        rid = _response_request_id(app)
        assert "\r" not in rid and "\n" not in rid
        assert rid != "evil"

    @pytest.mark.asyncio
    async def test_overlong_request_id_capped(self):
        """Values longer than 128 chars are truncated."""
        from api.middleware.request_context import _MAX_REQUEST_ID_LEN, RequestContextMiddleware

        app = _EchoApp()
        mw = RequestContextMiddleware(app=app)
        await mw(_make_scope(b"a" * 500), AsyncMock(), AsyncMock())
        assert len(_response_request_id(app)) <= _MAX_REQUEST_ID_LEN

    @pytest.mark.asyncio
    async def test_missing_header_generates_uuid(self):
        from api.middleware.request_context import RequestContextMiddleware

        app = _EchoApp()
        mw = RequestContextMiddleware(app=app)
        await mw(_make_scope(None), AsyncMock(), AsyncMock())
        assert len(_response_request_id(app)) == 36  # uuid4 format


# ──: HMAC middleware skip ────────────────────────────────────────────


class TestHmacMiddlewareSkippedWithoutSecret:
    def test_no_registration_when_no_secret_available(self):
        from api.middleware.setup import _configure_hmac

        app = MagicMock()
        settings = MagicMock()
        settings.api.hmac_signing_enabled = True
        settings.api.hmac_secret = None
        settings.api.get_api_key.return_value = None

        with patch("api.middleware.setup.log") as mock_log:
            _configure_hmac(app, settings)

        app.add_middleware.assert_not_called()
        mock_log.error.assert_called_once()

    def test_registers_when_api_key_fallback_available(self):
        from api.middleware.setup import _configure_hmac

        app = MagicMock()
        settings = MagicMock()
        settings.api.hmac_signing_enabled = True
        settings.api.hmac_secret = None
        settings.api.get_api_key.return_value = "fallback-key"

        _configure_hmac(app, settings)
        app.add_middleware.assert_called_once()


# ── analytics briefings logging ────────────────────────────────────


class TestBriefingsErrorLogging:
    @pytest.mark.asyncio
    async def test_failure_is_logged_and_degraded_response_returned(self):
        from api.endpoints import analytics

        with (
            patch.object(
                analytics,
                "_get_analytics_storage",
                side_effect=RuntimeError("db down"),
            ),
            patch.object(analytics, "log") as mock_log,
        ):
            result = await analytics.get_briefings(date=None, limit=10, _="k")

        assert result.data == {"briefings": [], "total": 0}
        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.kwargs["exc_type"] == "RuntimeError"


# ── GlobalSearchEngine.get_drift_deps ──────────────────────────────


class TestGetDriftDeps:
    def test_raises_when_llm_missing(self):
        from modules.knowledge.search.engines.global_search import GlobalSearchEngine

        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=None)
        with pytest.raises(RuntimeError, match="LLM"):
            engine.get_drift_deps()

    def test_returns_deps_when_llm_configured(self):
        from modules.knowledge.search.engines.global_search import GlobalSearchEngine

        cb = MagicMock()
        llm = object()
        engine = GlobalSearchEngine(context_builder=cb, llm=llm)
        assert engine.get_drift_deps() == (cb, llm)

    @pytest.mark.asyncio
    async def test_endpoint_returns_503_when_llm_not_configured(self):
        import api.endpoints.content.search as search_module
        from api.endpoints.content.search import DriftSearchRequest, search_drift
        from modules.knowledge.search.engines.global_search import GlobalSearchEngine

        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=None)
        request = MagicMock()
        body = DriftSearchRequest(query="test")
        fastapi_http = __import__("fastapi").HTTPException

        with pytest.raises(fastapi_http) as exc_info:
            await search_drift(
                request=request,
                body=body,
                _="k",
                local_engine=MagicMock(),
                global_engine=engine,
            )
        assert exc_info.value.status_code == 503
        # silence unused-import guard
        assert search_module is not None


# ── graph get_entity ───────────────────────────────────────────────


class TestGraphEntityNoDoubleDecode:
    @pytest.mark.asyncio
    async def test_name_passed_through_verbatim(self):
        from api.endpoints.graph.graph import get_entity

        repo = MagicMock()
        repo.get_entity = AsyncMock(
            return_value={
                "id": "e1",
                "canonical_name": "A%2FB",
                "type": "PERSON",
                "aliases": None,
                "description": None,
                "updated_at": None,
            }
        )
        repo.get_entity_relations = AsyncMock(return_value=[])
        repo.get_related_entities = AsyncMock(return_value=[])
        repo.get_entity_articles = AsyncMock(return_value=[])

        await get_entity(name="A%2FB", limit=10, _="k", graph_repo=repo)
        # name reaches the repository exactly as received
        repo.get_entity.assert_awaited_once_with("A%2FB")


# ── LLM usage shared query filter forwarding ───────────────────────


class TestLlmUsageFilterForwarding:
    @pytest.mark.asyncio
    async def test_provider_branch_forwards_all_filters(self):
        from api.endpoints._llm_usage_shared import query_llm_usage

        repo = MagicMock()
        repo.get_by_provider = AsyncMock(return_value=[])
        await query_llm_usage(
            repo,
            from_=MagicMock(),
            to=MagicMock(),
            group_by="provider",
            granularity="daily",
            provider="openai",
            model="gpt-4",
            llm_type="chat",
            call_point="pipeline",
        )
        kwargs = repo.get_by_provider.await_args.kwargs
        assert kwargs["model"] == "gpt-4"
        assert kwargs["call_point"] == "pipeline"
        assert kwargs["llm_type"] == "chat"

    @pytest.mark.asyncio
    async def test_model_branch_forwards_all_filters(self):
        from api.endpoints._llm_usage_shared import query_llm_usage

        repo = MagicMock()
        repo.get_by_model = AsyncMock(return_value=[])
        await query_llm_usage(
            repo,
            from_=MagicMock(),
            to=MagicMock(),
            group_by="model",
            granularity="daily",
            provider="openai",
            model="gpt-4",
            llm_type="chat",
            call_point="pipeline",
        )
        kwargs = repo.get_by_model.await_args.kwargs
        assert kwargs["provider"] == "openai"
        assert kwargs["llm_type"] == "chat"
        assert kwargs["call_point"] == "pipeline"

    @pytest.mark.asyncio
    async def test_call_point_branch_forwards_all_filters(self):
        from api.endpoints._llm_usage_shared import query_llm_usage

        repo = MagicMock()
        repo.get_by_call_point = AsyncMock(return_value=[])
        await query_llm_usage(
            repo,
            from_=MagicMock(),
            to=MagicMock(),
            group_by="call_point",
            granularity="daily",
            provider="openai",
            model="gpt-4",
            llm_type="chat",
            call_point=None,
        )
        kwargs = repo.get_by_call_point.await_args.kwargs
        assert kwargs["provider"] == "openai"
        assert kwargs["model"] == "gpt-4"
        assert kwargs["llm_type"] == "chat"


# ── SSE stream cancels the processing task on disconnect ───────────


class TestSseProcessingTaskCancellation:
    @pytest.mark.asyncio
    async def test_generator_close_cancels_processing_task(self):
        from api.endpoints.content import pipeline as pipeline_module

        cancelled_flag = {"value": False}
        release = asyncio.Event()

        async def slow_process(url, task_id, crawler, pipeline):
            try:
                await release.wait()  # parks inside the task until cancelled
            except asyncio.CancelledError:
                cancelled_flag["value"] = True
                raise
            return ""

        cache = MagicMock()
        cache.hget = AsyncMock(return_value=None)
        cache.hset = AsyncMock()

        container = MagicMock()
        container.crawler.return_value = MagicMock()
        container.pipeline.return_value = MagicMock()

        with (
            patch.object(pipeline_module, "_do_process", slow_process),
            patch("container.get_container", return_value=container),
        ):
            gen = pipeline_module._stream_url_processing(
                url="https://example.com/a", task_id="t-1", cache=cache
            )
            first = await gen.__anext__()  # "log" start event
            assert "Pipeline started" in first
            # Drive the generator into the inner try (creates the processing
            # task, parks slow_process, yields a heartbeat) before closing.
            second = await asyncio.wait_for(gen.__anext__(), timeout=5.0)
            assert "heartbeat" in second
            await asyncio.sleep(0.01)
            await gen.aclose()  # simulates client disconnect

        await asyncio.sleep(0)
        assert cancelled_flag["value"] is True


class TestCorsProductionOriginPolicy:
    """Production CORS misconfiguration must fail fast."""

    @staticmethod
    def _settings(environment: str) -> MagicMock:
        settings = MagicMock()
        settings.environment = environment
        return settings

    @staticmethod
    def _app() -> MagicMock:
        return MagicMock()

    def test_production_multiple_origins_raises(self, monkeypatch):
        from api.middleware.setup import _configure_cors

        monkeypatch.setenv("CORS_ORIGINS", "https://a.com,https://b.com")
        with pytest.raises(ValueError, match="multiple origins in production"):
            _configure_cors(self._app(), self._settings("production"))

    def test_production_single_origin_ok(self, monkeypatch):
        from api.middleware.setup import _configure_cors

        monkeypatch.setenv("CORS_ORIGINS", "https://a.com")
        app = self._app()
        _configure_cors(app, self._settings("production"))
        app.add_middleware.assert_called_once()

    def test_production_no_origins_disables_cors(self, monkeypatch):
        from api.middleware.setup import _configure_cors

        monkeypatch.setenv("CORS_ORIGINS", "")
        app = self._app()
        _configure_cors(app, self._settings("production"))
        kwargs = app.add_middleware.call_args.kwargs
        assert kwargs["allow_origins"] == []
        assert kwargs["allow_credentials"] is False

    def test_development_multiple_origins_allowed(self, monkeypatch):
        from api.middleware.setup import _configure_cors

        monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080")
        app = self._app()
        _configure_cors(app, self._settings("development"))
        kwargs = app.add_middleware.call_args.kwargs
        assert len(kwargs["allow_origins"]) == 2
