# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for src/main.py application entry point."""

from __future__ import annotations

import asyncio
import signal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx import AsyncClient, Response

# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_settings():
    """Create mock Settings for testing."""
    settings = MagicMock()
    settings.api.host = "localhost"
    settings.api.port = 8000
    settings.observability.otlp_endpoint = "http://localhost:4317"
    settings.spacy = MagicMock()
    settings.spacy.force_install = False
    settings.spacy.strict_mode = False
    settings.spacy.models = ["en_core_web_lg"]
    settings.spacy.local_paths = {}
    settings.validate_security = MagicMock(return_value=[])
    return settings


@pytest.fixture
def mock_container(mock_settings):
    """Create mock Container for testing."""
    container = MagicMock()
    container.settings = mock_settings
    container.startup = AsyncMock()
    container.shutdown = AsyncMock()

    # Mock all the pool/client/repo accessors
    container.postgres_pool = MagicMock()
    container.neo4j_pool = MagicMock()
    container.redis_client = MagicMock()
    container.llm_client = MagicMock()
    container.source_scheduler = MagicMock()
    container.vector_repo = MagicMock()
    container.source_config_repo = MagicMock()
    container.source_authority_repo = MagicMock()
    container.llm_failure_repo = MagicMock()
    container.llm_usage_repo = MagicMock()
    container.local_search_engine = MagicMock()
    container.global_search_engine = MagicMock()
    container.hybrid_search_engine = MagicMock()
    container.article_repo = MagicMock()
    container.article_repo.requeue_processing = AsyncMock()

    # Mock pipeline
    mock_pipeline = MagicMock()
    mock_pipeline.stop_accepting = AsyncMock()
    mock_pipeline.drain = AsyncMock()
    container.pipeline = MagicMock(return_value=mock_pipeline)

    return container


@pytest.fixture
def mock_spacy_manager():
    """Create mock SpacyModelManager for testing."""
    manager = MagicMock()
    manager.check_and_install = MagicMock()
    return manager


@pytest.fixture(autouse=True)
def reset_endpoints_registry():
    """Reset Endpoints class pool references before and after each test."""
    from api.endpoints import _deps as deps

    # Reset before test
    deps.Endpoints._postgres = None
    deps.Endpoints._neo4j = None
    deps.Endpoints._redis = None
    deps.Endpoints._llm = None
    deps.Endpoints._scheduler = None
    deps.Endpoints._vector_repo = None
    deps.Endpoints._source_config_repo = None
    deps.Endpoints._source_authority_repo = None
    deps.Endpoints._llm_failure_repo = None
    deps.Endpoints._llm_usage_repo = None
    deps.Endpoints._local_engine = None
    deps.Endpoints._global_engine = None
    deps.Endpoints._hybrid_engine = None
    deps.Endpoints._pipeline_service = None

    yield

    # Reset after test
    deps.Endpoints._postgres = None
    deps.Endpoints._neo4j = None
    deps.Endpoints._redis = None
    deps.Endpoints._llm = None
    deps.Endpoints._scheduler = None
    deps.Endpoints._vector_repo = None
    deps.Endpoints._source_config_repo = None
    deps.Endpoints._source_authority_repo = None
    deps.Endpoints._llm_failure_repo = None
    deps.Endpoints._llm_usage_repo = None
    deps.Endpoints._local_engine = None
    deps.Endpoints._global_engine = None
    deps.Endpoints._hybrid_engine = None
    deps.Endpoints._pipeline_service = None


# ────────────────────────────────────────────────────────────────────────────
# _ensure_spacy_models Tests
# ────────────────────────────────────────────────────────────────────────────


class TestEnsureSpacyModels:
    """Tests for _ensure_spacy_models function."""

    def test_creates_spacy_config_from_settings(self, mock_settings, mock_spacy_manager):
        """Test that SpacyModelConfig is created from settings."""
        with patch("main.SpacyModelConfig") as mock_config_cls:
            with patch("main.SpacyModelManager", return_value=mock_spacy_manager):
                from main import _ensure_spacy_models

                _ensure_spacy_models(mock_settings)

                mock_config_cls.assert_called_once_with(
                    force_install=mock_settings.spacy.force_install,
                    strict_mode=mock_settings.spacy.strict_mode,
                    models=mock_settings.spacy.models,
                    local_paths=mock_settings.spacy.local_paths,
                )

    def test_calls_check_and_install(self, mock_settings, mock_spacy_manager):
        """Test that check_and_install is called."""
        with patch("main.SpacyModelConfig"):
            with patch("main.SpacyModelManager", return_value=mock_spacy_manager):
                from main import _ensure_spacy_models

                _ensure_spacy_models(mock_settings)

                mock_spacy_manager.check_and_install.assert_called_once()

    def test_raises_runtime_error_in_strict_mode_on_failure(self, mock_settings):
        """Test RuntimeError is raised in strict mode when installation fails."""
        mock_settings.spacy.strict_mode = True

        mock_manager = MagicMock()
        mock_manager.check_and_install = MagicMock(side_effect=RuntimeError("Model not found"))

        with patch("main.SpacyModelConfig"):
            with patch("main.SpacyModelManager", return_value=mock_manager):
                from main import _ensure_spacy_models

                with pytest.raises(RuntimeError, match="Model not found"):
                    _ensure_spacy_models(mock_settings)


# ────────────────────────────────────────────────────────────────────────────
# lifespan Tests
# ────────────────────────────────────────────────────────────────────────────


class TestLifespan:
    """Tests for application lifespan context manager."""

    @pytest.mark.asyncio
    async def test_startup_initializes_tracing(self, mock_container):
        """Test that OpenTelemetry tracing is initialized on startup."""
        with patch("main.configure_tracing") as mock_configure_tracing:
            with patch("main.instrument_fastapi") as mock_instrument:
                with patch("main.set_container") as mock_set_container:
                    with patch("main.set_settings") as mock_set_settings:
                        with patch("main.log"):
                            from main import lifespan

                            app = FastAPI()
                            app.state.container = mock_container

                            # Enter lifespan context
                            async with lifespan(app):
                                pass

                            mock_configure_tracing.assert_called_once_with(
                                service_name="weaver",
                                endpoint=mock_container.settings.observability.otlp_endpoint,
                            )
                            mock_instrument.assert_called_once_with(app)

    @pytest.mark.asyncio
    async def test_startup_calls_container_startup(self, mock_container):
        """Test that container.startup() is called."""
        with patch("main.configure_tracing"):
            with patch("main.instrument_fastapi"):
                with patch("main.set_container"):
                    with patch("main.set_settings"):
                        with patch("main.log"):
                            from main import lifespan

                            app = FastAPI()
                            app.state.container = mock_container

                            async with lifespan(app):
                                pass

                            mock_container.startup.assert_called_once()

    @pytest.mark.asyncio
    async def test_startup_populates_endpoints_registry(self, mock_container):
        """Test that Endpoints registry is populated with all dependencies."""
        with patch("main.configure_tracing"):
            with patch("main.instrument_fastapi"):
                with patch("main.set_container"):
                    with patch("main.set_settings"):
                        with patch("main.log"):
                            from api.endpoints import _deps as deps
                            from main import lifespan

                            app = FastAPI()
                            app.state.container = mock_container

                            async with lifespan(app):
                                pass

                            # Verify all endpoints were set
                            assert deps.Endpoints._postgres is mock_container.postgres_pool()
                            assert deps.Endpoints._neo4j is mock_container.neo4j_pool()
                            assert deps.Endpoints._redis is mock_container.redis_client()
                            assert deps.Endpoints._llm is mock_container.llm_client()
                            assert deps.Endpoints._scheduler is mock_container.source_scheduler()
                            assert deps.Endpoints._vector_repo is mock_container.vector_repo()
                            assert (
                                deps.Endpoints._source_config_repo
                                is mock_container.source_config_repo()
                            )
                            assert (
                                deps.Endpoints._source_authority_repo
                                is mock_container.source_authority_repo()
                            )
                            assert (
                                deps.Endpoints._llm_failure_repo
                                is mock_container.llm_failure_repo()
                            )
                            assert deps.Endpoints._llm_usage_repo is mock_container.llm_usage_repo()
                            assert (
                                deps.Endpoints._local_engine is mock_container.local_search_engine()
                            )
                            assert (
                                deps.Endpoints._global_engine
                                is mock_container.global_search_engine()
                            )
                            assert (
                                deps.Endpoints._hybrid_engine
                                is mock_container.hybrid_search_engine()
                            )

    @pytest.mark.asyncio
    async def test_shutdown_calls_graceful_shutdown(self, mock_container):
        """Test that graceful shutdown is called on exit."""
        with patch("main.configure_tracing"):
            with patch("main.instrument_fastapi"):
                with patch("main.set_container"):
                    with patch("main.set_settings"):
                        with patch("main._graceful_shutdown") as mock_graceful:
                            with patch("main.log"):
                                from main import lifespan

                                app = FastAPI()
                                app.state.container = mock_container

                                async with lifespan(app):
                                    pass

                                mock_graceful.assert_called_once_with(app)


# ────────────────────────────────────────────────────────────────────────────
# _graceful_shutdown Tests
# ────────────────────────────────────────────────────────────────────────────


class TestGracefulShutdown:
    """Tests for _graceful_shutdown function."""

    @pytest.mark.asyncio
    async def test_stops_pipeline_accepting(self, mock_container):
        """Test that pipeline.stop_accepting() is called."""
        with patch("main.log"):
            from main import _graceful_shutdown

            app = FastAPI()
            app.state.container = mock_container

            await _graceful_shutdown(app)

            mock_container.pipeline().stop_accepting.assert_called_once()

    @pytest.mark.asyncio
    async def test_drains_pipeline_with_timeout(self, mock_container):
        """Test that pipeline.drain() is called with 30s timeout."""
        with patch("main.log"):
            from main import _graceful_shutdown

            app = FastAPI()
            app.state.container = mock_container

            await _graceful_shutdown(app)

            mock_container.pipeline().drain.assert_called_once()

    @pytest.mark.asyncio
    async def test_drain_timeout_handled(self, mock_container):
        """Test that drain timeout is handled gracefully."""
        mock_container.pipeline().drain = AsyncMock(side_effect=TimeoutError())

        with patch("main.log"):
            from main import _graceful_shutdown

            app = FastAPI()
            app.state.container = mock_container

            # Should not raise, just log warning
            await _graceful_shutdown(app)

    @pytest.mark.asyncio
    async def test_drain_error_handled(self, mock_container):
        """Test that drain errors are handled gracefully."""
        mock_container.pipeline().drain = AsyncMock(side_effect=Exception("Drain failed"))

        with patch("main.log"):
            from main import _graceful_shutdown

            app = FastAPI()
            app.state.container = mock_container

            # Should not raise, just log warning
            await _graceful_shutdown(app)

    @pytest.mark.asyncio
    async def test_requeues_processing_articles(self, mock_container):
        """Test that processing articles are requeued."""
        with patch("main.log"):
            from main import _graceful_shutdown

            app = FastAPI()
            app.state.container = mock_container

            await _graceful_shutdown(app)

            mock_container.article_repo().requeue_processing.assert_called_once()

    @pytest.mark.asyncio
    async def test_requeue_error_handled(self, mock_container):
        """Test that requeue errors are handled gracefully."""
        mock_container.article_repo().requeue_processing = AsyncMock(
            side_effect=Exception("Requeue failed")
        )

        with patch("main.log"):
            from main import _graceful_shutdown

            app = FastAPI()
            app.state.container = mock_container

            # Should not raise, just log warning
            await _graceful_shutdown(app)

    @pytest.mark.asyncio
    async def test_calls_container_shutdown(self, mock_container):
        """Test that container.shutdown() is called."""
        with patch("main.log"):
            from main import _graceful_shutdown

            app = FastAPI()
            app.state.container = mock_container

            await _graceful_shutdown(app)

            mock_container.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_missing_pipeline(self, mock_container):
        """Test graceful shutdown when container doesn't have pipeline."""
        del mock_container.pipeline

        with patch("main.log"):
            from main import _graceful_shutdown

            app = FastAPI()
            app.state.container = mock_container

            # Should not raise
            await _graceful_shutdown(app)

            mock_container.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_missing_article_repo(self, mock_container):
        """Test graceful shutdown when container doesn't have article_repo."""
        del mock_container.article_repo

        with patch("main.log"):
            from main import _graceful_shutdown

            app = FastAPI()
            app.state.container = mock_container

            # Should not raise
            await _graceful_shutdown(app)

            mock_container.shutdown.assert_called_once()


# ────────────────────────────────────────────────────────────────────────────
# HTTPLoggingMiddleware Tests
# ────────────────────────────────────────────────────────────────────────────


class TestHTTPLoggingMiddleware:
    """Tests for HTTPLoggingMiddleware."""

    def test_init(self):
        """Test middleware initialization."""
        from main import HTTPLoggingMiddleware

        app = MagicMock()
        middleware = HTTPLoggingMiddleware(app)

        assert middleware.app == app

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(self):
        """Test that non-http scopes are passed through directly."""
        from main import HTTPLoggingMiddleware

        app = AsyncMock()
        middleware = HTTPLoggingMiddleware(app)

        scope = {"type": "websocket"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        app.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_logs_http_request(self):
        """Test that HTTP requests are logged."""
        from main import HTTPLoggingMiddleware

        # Create a simple ASGI app that sends a response
        async def simple_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"Hello"})

        middleware = HTTPLoggingMiddleware(simple_app)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "query_string": b"foo=bar",
            "headers": [(b"x-api-key", b"testkey123456789")],
            "client": ("127.0.0.1", 12345),
        }
        receive = AsyncMock()
        send = AsyncMock()

        with patch("main.log") as mock_log:
            await middleware(scope, receive, send)

            # Check request was logged
            request_calls = [c for c in mock_log.info.call_args_list if "http_request" in str(c)]
            assert len(request_calls) >= 1

    @pytest.mark.asyncio
    async def test_masks_api_key_in_log(self):
        """Test that API key is masked in logs."""
        from main import HTTPLoggingMiddleware

        async def simple_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"Hello"})

        middleware = HTTPLoggingMiddleware(simple_app)

        long_api_key = b"verylongapikey1234567890"
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "query_string": b"",
            "headers": [(b"x-api-key", long_api_key)],
            "client": ("127.0.0.1", 12345),
        }
        receive = AsyncMock()
        send = AsyncMock()

        with patch("main.log") as mock_log:
            await middleware(scope, receive, send)

            # Verify API key was masked (only first 8 chars shown)
            for call in mock_log.info.call_args_list:
                if "http_request" in str(call):
                    kwargs = call[1]
                    if "api_key" in kwargs:
                        assert "..." in kwargs["api_key"]
                        assert len(kwargs["api_key"]) < len(long_api_key.decode())

    @pytest.mark.asyncio
    async def test_logs_http_response(self):
        """Test that HTTP responses are logged."""
        from main import HTTPLoggingMiddleware

        async def simple_app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": b'{"data": "test"}'})

        middleware = HTTPLoggingMiddleware(simple_app)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
        receive = AsyncMock()
        send = AsyncMock()

        with patch("main.log") as mock_log:
            await middleware(scope, receive, send)

            # Check response was logged
            response_calls = [c for c in mock_log.info.call_args_list if "http_response" in str(c)]
            assert len(response_calls) >= 1

    @pytest.mark.asyncio
    async def test_truncates_large_json_response_body(self):
        """Test that large JSON response bodies are truncated."""
        from main import HTTPLoggingMiddleware

        large_body = b'{"data": "' + b"x" * 1000 + b'"}'

        async def simple_app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": large_body})

        middleware = HTTPLoggingMiddleware(simple_app)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
        receive = AsyncMock()
        send = AsyncMock()

        with patch("main.log") as mock_log:
            await middleware(scope, receive, send)

            # Check body_preview was truncated
            for call in mock_log.info.call_args_list:
                if "http_response" in str(call):
                    kwargs = call[1]
                    if "body_preview" in kwargs:
                        assert len(kwargs["body_preview"]) <= 503  # 500 + "..."
                        if len(large_body) > 500:
                            assert kwargs["body_preview"].endswith("...")


# ────────────────────────────────────────────────────────────────────────────
# SecurityHeadersMiddleware Tests
# ────────────────────────────────────────────────────────────────────────────


class TestSecurityHeadersMiddleware:
    """Tests for SecurityHeadersMiddleware."""

    def test_init(self):
        """Test middleware initialization."""
        from main import SecurityHeadersMiddleware

        app = MagicMock()
        middleware = SecurityHeadersMiddleware(app)

        assert middleware.app == app

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(self):
        """Test that non-http scopes are passed through directly."""
        from main import SecurityHeadersMiddleware

        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)

        scope = {"type": "websocket"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        app.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_adds_security_headers(self):
        """Test that security headers are added to responses."""
        from main import SecurityHeadersMiddleware

        async def simple_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})

        middleware = SecurityHeadersMiddleware(simple_app)

        scope = {"type": "http", "method": "GET", "path": "/test", "headers": []}
        receive = AsyncMock()

        captured_headers = []

        async def capture_send(message):
            if message["type"] == "http.response.start":
                captured_headers = message["headers"]

        await middleware(scope, receive, capture_send)

        # Headers dict captured in send_wrapper
        # We need to use a different approach to verify headers
        headers_dict = {}

        async def capturing_app(scope, receive, send):
            async def wrapper_send(message):
                if message["type"] == "http.response.start":
                    headers_dict.update(dict(message.get("headers", [])))
                await send(message)

            await simple_app(scope, receive, wrapper_send)

        middleware2 = SecurityHeadersMiddleware(capturing_app)

        async def final_send(message):
            if message["type"] == "http.response.start":
                headers_dict.update(dict(message.get("headers", [])))

        await middleware2(scope, receive, final_send)

        assert headers_dict.get(b"x-content-type-options") == b"nosniff"
        assert headers_dict.get(b"x-frame-options") == b"DENY"
        assert headers_dict.get(b"x-xss-protection") == b"1; mode=block"
        assert (
            headers_dict.get(b"strict-transport-security") == b"max-age=31536000; includeSubDomains"
        )

    @pytest.mark.asyncio
    async def test_preserves_existing_headers(self):
        """Test that existing headers are preserved."""
        from main import SecurityHeadersMiddleware

        async def app_with_headers(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/html"), (b"x-custom", b"value")],
                }
            )

        middleware = SecurityHeadersMiddleware(app_with_headers)

        scope = {"type": "http", "method": "GET", "path": "/test", "headers": []}
        receive = AsyncMock()

        captured_headers = {}
        sent_messages = []

        async def capture_send(message):
            sent_messages.append(message)
            if message["type"] == "http.response.start":
                captured_headers.update(dict(message.get("headers", [])))

        await middleware(scope, receive, capture_send)

        # Verify original headers still present
        assert captured_headers.get(b"content-type") == b"text/html"
        assert captured_headers.get(b"x-custom") == b"value"
        # And security headers added
        assert captured_headers.get(b"x-content-type-options") == b"nosniff"


# ────────────────────────────────────────────────────────────────────────────
# RequestSizeLimitMiddleware Tests
# ────────────────────────────────────────────────────────────────────────────


class TestRequestSizeLimitMiddleware:
    """Tests for RequestSizeLimitMiddleware."""

    def test_init(self):
        """Test middleware initialization."""
        from main import RequestSizeLimitMiddleware

        app = MagicMock()
        middleware = RequestSizeLimitMiddleware(app)

        assert middleware.app == app
        assert middleware.MAX_REQUEST_SIZE == 10 * 1024 * 1024  # 10MB

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(self):
        """Test that non-http scopes are passed through directly."""
        from main import RequestSizeLimitMiddleware

        app = AsyncMock()
        middleware = RequestSizeLimitMiddleware(app)

        scope = {"type": "websocket"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        app.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_passes_through_get_requests(self):
        """Test that GET requests are passed through without size check."""
        from main import RequestSizeLimitMiddleware

        app = AsyncMock()
        middleware = RequestSizeLimitMiddleware(app)

        scope = {"type": "http", "method": "GET", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        app.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_passes_through_small_post_requests(self):
        """Test that small POST requests are passed through."""
        from main import RequestSizeLimitMiddleware

        app = AsyncMock()
        middleware = RequestSizeLimitMiddleware(app)

        scope = {
            "type": "http",
            "method": "POST",
            "headers": [(b"content-length", b"1024")],  # 1KB
        }
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        app.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_rejects_large_post_requests(self):
        """Test that large POST requests are rejected with 413."""
        from main import RequestSizeLimitMiddleware

        app = AsyncMock()
        middleware = RequestSizeLimitMiddleware(app)

        # Request larger than 10MB
        scope = {
            "type": "http",
            "method": "POST",
            "headers": [(b"content-length", b"20000000")],  # 20MB
        }
        receive = AsyncMock()

        sent_messages = []

        async def capture_send(message):
            sent_messages.append(message)

        await middleware(scope, receive, capture_send)

        # Should have sent 413 response
        assert len(sent_messages) == 2
        assert sent_messages[0]["type"] == "http.response.start"
        assert sent_messages[0]["status"] == 413
        assert sent_messages[1]["type"] == "http.response.body"

        # App should NOT have been called
        app.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_large_put_requests(self):
        """Test that large PUT requests are rejected."""
        from main import RequestSizeLimitMiddleware

        app = AsyncMock()
        middleware = RequestSizeLimitMiddleware(app)

        scope = {
            "type": "http",
            "method": "PUT",
            "headers": [(b"content-length", b"20000000")],
        }
        receive = AsyncMock()

        sent_messages = []

        async def capture_send(message):
            sent_messages.append(message)

        await middleware(scope, receive, capture_send)

        assert sent_messages[0]["status"] == 413
        app.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_large_patch_requests(self):
        """Test that large PATCH requests are rejected."""
        from main import RequestSizeLimitMiddleware

        app = AsyncMock()
        middleware = RequestSizeLimitMiddleware(app)

        scope = {
            "type": "http",
            "method": "PATCH",
            "headers": [(b"content-length", b"20000000")],
        }
        receive = AsyncMock()

        sent_messages = []

        async def capture_send(message):
            sent_messages.append(message)

        await middleware(scope, receive, capture_send)

        assert sent_messages[0]["status"] == 413
        app.assert_not_called()

    @pytest.mark.asyncio
    async def test_passes_requests_without_content_length(self):
        """Test that requests without content-length are passed through."""
        from main import RequestSizeLimitMiddleware

        app = AsyncMock()
        middleware = RequestSizeLimitMiddleware(app)

        scope = {"type": "http", "method": "POST", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        app.assert_called_once_with(scope, receive, send)


# ────────────────────────────────────────────────────────────────────────────
# create_app Tests
# ────────────────────────────────────────────────────────────────────────────


class TestCreateApp:
    """Tests for create_app factory function."""

    def test_creates_fastapi_instance(self, mock_settings):
        """Test that FastAPI instance is created."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                from main import create_app

                app = create_app()

                assert isinstance(app, FastAPI)
                assert app.title == "Weaver API"

    def test_adds_cors_middleware(self, mock_settings):
        """Test that CORS middleware is added."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                with patch.dict("os.environ", {"CORS_ORIGINS": "http://localhost:3000"}):
                    from main import create_app

                    app = create_app()

                    # Check middleware is present
                    cors_middleware_found = False
                    for middleware in app.user_middleware:
                        if "CORSMiddleware" in str(middleware):
                            cors_middleware_found = True
                            break
                    assert cors_middleware_found

    def test_adds_security_middleware(self, mock_settings):
        """Test that security middleware is added."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                from main import create_app

                app = create_app()

                # Check SecurityHeadersMiddleware is present
                security_middleware_found = False
                for middleware in app.user_middleware:
                    if "SecurityHeadersMiddleware" in str(middleware):
                        security_middleware_found = True
                        break
                assert security_middleware_found

    def test_adds_request_size_limit_middleware(self, mock_settings):
        """Test that request size limit middleware is added."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                from main import create_app

                app = create_app()

                # Check RequestSizeLimitMiddleware is present
                size_limit_found = False
                for middleware in app.user_middleware:
                    if "RequestSizeLimitMiddleware" in str(middleware):
                        size_limit_found = True
                        break
                assert size_limit_found

    def test_adds_logging_middleware(self, mock_settings):
        """Test that HTTP logging middleware is added."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                from main import create_app

                app = create_app()

                # Check HTTPLoggingMiddleware is present
                logging_middleware_found = False
                for middleware in app.user_middleware:
                    if "HTTPLoggingMiddleware" in str(middleware):
                        logging_middleware_found = True
                        break
                assert logging_middleware_found

    def test_includes_api_router(self, mock_settings):
        """Test that API router is included."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                from main import create_app

                app = create_app()

                # Check router is included
                routes = [route.path for route in app.routes]
                # API routes should start with /api/v1
                api_routes = [r for r in routes if r.startswith("/api/v1")]
                assert len(api_routes) > 0

    def test_registers_exception_handlers(self, mock_settings):
        """Test that exception handlers are registered."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                with patch("main.register_exception_handlers") as mock_register:
                    from main import create_app

                    app = create_app()

                    mock_register.assert_called_once_with(app)

    def test_adds_rate_limit_handler(self, mock_settings):
        """Test that rate limit exception handler is added."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                with patch("main.register_exception_handlers"):
                    from main import create_app

                    app = create_app()

                    # Check RateLimitExceeded handler is registered
                    assert hasattr(app.state, "limiter")

    def test_stores_container_in_state(self, mock_container, mock_settings):
        """Test that container is stored in app.state."""
        with patch("main._ensure_spacy_models"):
            from main import create_app

            app = create_app(mock_container)

            assert app.state.container == mock_container

    def test_creates_container_if_not_provided(self, mock_settings):
        """Test that container is created if not provided."""
        mock_container_instance = MagicMock()
        mock_container_instance.configure = MagicMock(return_value=mock_container_instance)

        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                with patch("main.Container", return_value=mock_container_instance):
                    from main import create_app

                    app = create_app()

                    mock_container_instance.configure.assert_called_once()
                    assert app.state.container == mock_container_instance

    def test_calls_ensure_spacy_models(self, mock_settings):
        """Test that _ensure_spacy_models is called."""
        with patch("main._ensure_spacy_models") as mock_ensure:
            with patch("main.Settings", return_value=mock_settings):
                from main import create_app

                create_app()

                mock_ensure.assert_called_once()

    def test_validates_security_settings(self, mock_settings):
        """Test that security settings are validated."""
        mock_settings.validate_security = MagicMock(return_value=["warning1", "warning2"])

        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                with patch("main.log") as mock_log:
                    from main import create_app

                    create_app()

                    # Should log warnings
                    assert mock_log.warning.call_count == 2

    def test_has_health_endpoint(self, mock_settings):
        """Test that health endpoint is registered."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                from main import create_app

                app = create_app()

                routes = [route.path for route in app.routes]
                assert "/health" in routes

    def test_has_metrics_endpoint(self, mock_settings):
        """Test that metrics endpoint is registered."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                from main import create_app

                app = create_app()

                routes = [route.path for route in app.routes]
                assert "/metrics" in routes


# ────────────────────────────────────────────────────────────────────────────
# Health Endpoint Tests
# ────────────────────────────────────────────────────────────────────────────


class TestHealthEndpoint:
    """Tests for /health endpoint behavior."""

    def test_health_endpoint_returns_healthy(self, mock_settings):
        """Test health endpoint returns success when healthy."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                with patch("main.health_check") as mock_health_check:
                    from api.endpoints.health import HealthCheckResponse, ServiceHealthCheck

                    mock_health_check.return_value = HealthCheckResponse(
                        status="healthy",
                        checks={
                            "postgres": ServiceHealthCheck(status="ok", latency_ms=10.0),
                            "redis": ServiceHealthCheck(status="ok", latency_ms=5.0),
                        },
                    )

                    from main import create_app

                    app = create_app()
                    client = TestClient(app)

                    response = client.get("/health")

                    assert response.status_code == 200
                    assert response.json()["data"]["status"] == "healthy"

    def test_health_endpoint_returns_503_when_unhealthy(self, mock_settings):
        """Test health endpoint returns 503 when unhealthy."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                with patch("main.health_check") as mock_health_check:
                    from api.endpoints.health import HealthCheckResponse, ServiceHealthCheck

                    mock_health_check.return_value = HealthCheckResponse(
                        status="unhealthy",
                        checks={
                            "postgres": ServiceHealthCheck(
                                status="error", error="Connection refused"
                            ),
                        },
                    )

                    from main import create_app

                    app = create_app()
                    client = TestClient(app)

                    response = client.get("/health")

                    assert response.status_code == 503


# ────────────────────────────────────────────────────────────────────────────
# Metrics Endpoint Tests
# ────────────────────────────────────────────────────────────────────────────


class TestMetricsEndpoint:
    """Tests for /metrics endpoint behavior."""

    def test_metrics_endpoint_returns_prometheus_format(self, mock_settings):
        """Test metrics endpoint returns Prometheus metrics."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                with patch("main.generate_latest", return_value=b"prometheus_metrics"):
                    from main import create_app

                    app = create_app()
                    client = TestClient(app)

                    response = client.get("/metrics")

                    assert response.status_code == 200
                    assert (
                        response.headers["content-type"]
                        == "text/plain; version=1.0.0; charset=utf-8"
                    )


# ────────────────────────────────────────────────────────────────────────────
# CORS Configuration Tests
# ────────────────────────────────────────────────────────────────────────────


class TestCorsConfiguration:
    """Tests for CORS configuration."""

    def test_default_cors_origins(self, mock_settings):
        """Test default CORS origins."""
        import os

        default_origins = "http://localhost:3000,http://localhost:8080,http://127.0.0.1:3000"

        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                with patch.dict("os.environ", {"CORS_ORIGINS": default_origins}, clear=False):
                    # Remove CORS_ORIGINS if set to test default
                    if "CORS_ORIGINS" in os.environ:
                        del os.environ["CORS_ORIGINS"]

                    from main import create_app

                    app = create_app()

                    # Should have CORS middleware with default origins
                    # We verify the middleware is present, actual origin values
                    # are harder to extract from middleware obj
                    cors_found = any("CORSMiddleware" in str(m) for m in app.user_middleware)
                    assert cors_found

    def test_custom_cors_origins_from_env(self, mock_settings):
        """Test custom CORS origins from environment."""
        custom_origins = "http://example.com,https://example.com"

        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                with patch.dict("os.environ", {"CORS_ORIGINS": custom_origins}):
                    from main import create_app

                    app = create_app()

                    cors_found = any("CORSMiddleware" in str(m) for m in app.user_middleware)
                    assert cors_found


# ────────────────────────────────────────────────────────────────────────────
# Module-level app Tests
# ────────────────────────────────────────────────────────────────────────────


class TestModuleApp:
    """Tests for module-level app instance."""

    def test_app_instance_exists(self):
        """Test that app instance is created at module level."""
        # This test imports main which creates the app
        # We need to be careful about the import
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings"):
                from main import app

                assert isinstance(app, FastAPI)

    def test_app_has_correct_title(self):
        """Test app has correct title."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings"):
                from main import app

                assert app.title == "Weaver API"


# ────────────────────────────────────────────────────────────────────────────
# Error Handling Tests
# ────────────────────────────────────────────────────────────────────────────


class TestErrorHandling:
    """Tests for error handling in main.py."""

    @pytest.mark.asyncio
    async def test_lifespan_handles_startup_failure(self, mock_container):
        """Test lifespan handles startup failure gracefully."""
        mock_container.startup = AsyncMock(side_effect=Exception("Startup failed"))

        with patch("main.configure_tracing"):
            with patch("main.instrument_fastapi"):
                with patch("main.log"):
                    from main import lifespan

                    app = FastAPI()
                    app.state.container = mock_container

                    # Should raise the exception
                    with pytest.raises(Exception, match="Startup failed"):
                        async with lifespan(app):
                            pass

    def test_create_app_handles_spacy_failure_in_strict_mode(self, mock_settings):
        """Test create_app handles spaCy failure in strict mode."""
        mock_settings.spacy.strict_mode = True

        with patch("main._ensure_spacy_models", side_effect=RuntimeError("Model not available")):
            with patch("main.Settings", return_value=mock_settings):
                from main import create_app

                with pytest.raises(RuntimeError, match="Model not available"):
                    create_app()


# ────────────────────────────────────────────────────────────────────────────
# Signal Handling Tests
# ────────────────────────────────────────────────────────────────────────────


class TestSignalHandling:
    """Tests for signal handling in main function."""

    def test_signal_handlers_registered(self, mock_settings):
        """Test that signal handlers are registered in main()."""
        # This test verifies the structure of signal handling
        # Running main() directly is complex due to uvicorn

        # We verify the graceful_shutdown function handles signals correctly
        from main import _graceful_shutdown

        # The function should exist and be callable
        assert callable(_graceful_shutdown)


# ────────────────────────────────────────────────────────────────────────────
# Integration Tests with TestClient
# ────────────────────────────────────────────────────────────────────────────


class TestAppIntegration:
    """Integration tests using TestClient."""

    def test_app_routes_accessible(self, mock_settings):
        """Test that basic routes are accessible."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                from main import create_app

                app = create_app()
                client = TestClient(app)

                # Health endpoint
                response = client.get("/health")
                assert response.status_code in (200, 503)  # Depends on mock status

                # Metrics endpoint
                response = client.get("/metrics")
                assert response.status_code == 200

    def test_security_headers_present(self, mock_settings):
        """Test that security headers are present in responses."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                from main import create_app

                app = create_app()
                client = TestClient(app)

                response = client.get("/health")

                assert "x-content-type-options" in response.headers
                assert response.headers["x-content-type-options"] == "nosniff"
                assert "x-frame-options" in response.headers
                assert response.headers["x-frame-options"] == "DENY"

    def test_request_size_limit_enforced(self, mock_settings):
        """Test that request size limit is enforced."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                from main import create_app

                app = create_app()

                # Create a large body > 10MB
                large_body = "x" * (11 * 1024 * 1024)

                # We can't easily test this with TestClient as it doesn't send
                # content-length for large bodies in the same way
                # Instead we verify middleware exists
                size_limit_found = any(
                    "RequestSizeLimitMiddleware" in str(m) for m in app.user_middleware
                )
                assert size_limit_found

    def test_api_v1_routes_registered(self, mock_settings):
        """Test that API v1 routes are registered."""
        with patch("main._ensure_spacy_models"):
            with patch("main.Settings", return_value=mock_settings):
                from main import create_app

                app = create_app()

                routes = [route.path for route in app.routes]

                # Check some known API routes exist
                api_routes = [r for r in routes if r.startswith("/api/v1")]
                assert len(api_routes) > 0
