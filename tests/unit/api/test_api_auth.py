# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for API authentication middleware (auth.py)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


class TestVerifyApiKeyEdgeCases:
    """Extended edge-case tests for verify_api_key beyond the basics in test_api.py."""

    @pytest.mark.asyncio
    async def test_empty_string_key_raises_403(self):
        """Test verify_api_key raises 403 when key is an empty string."""
        from api.middleware.auth import verify_api_key

        mock_settings = MagicMock()
        mock_settings.api.get_api_key.return_value = "valid-key"

        with patch("container.get_settings", return_value=mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(key="")
            assert exc_info.value.status_code == 403
            assert "Invalid API Key" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_whitespace_only_key_raises_403(self):
        """Test verify_api_key raises 403 when key contains only whitespace."""
        from api.middleware.auth import verify_api_key

        mock_settings = MagicMock()
        mock_settings.api.get_api_key.return_value = "valid-key"

        with patch("container.get_settings", return_value=mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(key="   ")
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_valid_key_returns_correct_string(self):
        """Test verify_api_key returns the validated key string."""
        from api.middleware.auth import verify_api_key

        mock_settings = MagicMock()
        mock_settings.api.get_api_key.return_value = "my-secret-key"

        with patch("container.get_settings", return_value=mock_settings):
            result = await verify_api_key(key="my-secret-key")
            assert result == "my-secret-key"

    @pytest.mark.asyncio
    async def test_compare_digest_called_for_key_comparison(self):
        """Test that secrets.compare_digest is used (not string equality) for key comparison."""
        from api.middleware.auth import verify_api_key

        mock_settings = MagicMock()
        mock_settings.api.get_api_key.return_value = "expected-key"

        with (
            patch("container.get_settings", return_value=mock_settings),
            patch("api.middleware.auth.secrets.compare_digest", return_value=False) as mock_compare,
        ):
            with pytest.raises(HTTPException):
                await verify_api_key(key="wrong-key")
            # Verify compare_digest was called with the provided key and expected key
            mock_compare.assert_called_once_with("wrong-key", "expected-key")

    @pytest.mark.asyncio
    async def test_compare_digest_called_with_valid_key(self):
        """Test compare_digest is called and returns True for valid key."""
        from api.middleware.auth import verify_api_key

        mock_settings = MagicMock()
        mock_settings.api.get_api_key.return_value = "correct-key"

        with (
            patch("container.get_settings", return_value=mock_settings),
            patch("api.middleware.auth.secrets.compare_digest", return_value=True) as mock_compare,
        ):
            result = await verify_api_key(key="correct-key")
            mock_compare.assert_called_once_with("correct-key", "correct-key")
            assert result == "correct-key"

    @pytest.mark.asyncio
    async def test_timing_attack_safety_using_compare_digest(self):
        """Verify the implementation uses secrets.compare_digest for timing-attack safety.

        This ensures the auth function does not use plain `==` comparison which could
        leak timing information about the expected key through response time variation.
        """
        # Read the source to confirm compare_digest is used
        import inspect

        from api.middleware.auth import verify_api_key

        source = inspect.getsource(verify_api_key)
        assert (
            "compare_digest" in source
        ), "verify_api_key must use secrets.compare_digest to prevent timing attacks"
        assert (
            "==" not in source.split("compare_digest")[0][-50:]
        ), "No plain == comparison should be used on the API key"


class TestApiKeyHeader:
    """Tests for the API key header definition."""

    def test_api_key_header_name_is_x_api_key(self):
        """Test that the header name is X-API-Key."""
        from api.middleware.auth import api_key_header

        assert api_key_header.model.name == "X-API-Key"

    def test_api_key_header_auto_error_false(self):
        """Test that auto_error is False so missing header does not raise immediately.

        auto_error=False means FastAPI won't auto-raise HTTP 403 — we handle None manually.
        """
        from api.middleware.auth import api_key_header

        # auto_error=False on the instance means FastAPI won't auto-raise 403
        assert api_key_header.auto_error is False

    def test_api_key_header_is_not_none(self):
        """Test api_key_header is not None."""
        from api.middleware.auth import api_key_header

        assert api_key_header is not None


class TestAuthMiddlewareIntegration:
    """HTTP-level integration tests for auth middleware using FastAPI TestClient."""

    def test_articles_endpoint_without_api_key_returns_401(self):
        """Test GET /articles without X-API-Key returns 401."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.endpoints.articles import router

        app = FastAPI()
        app.include_router(router)

        # Override the dependency to return a mock pool
        from unittest.mock import MagicMock

        from api.dependencies import get_relational_pool

        mock_pool = MagicMock()
        app.dependency_overrides[get_relational_pool] = lambda: mock_pool

        with TestClient(app) as client:
            response = client.get("/articles")
            assert response.status_code == 401

    def test_articles_endpoint_with_wrong_api_key_returns_403(self):
        """Test GET /articles with invalid X-API-Key returns 403."""
        from unittest.mock import MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.dependencies import get_relational_pool
        from api.endpoints.articles import router

        app = FastAPI()
        app.include_router(router)

        mock_pool = MagicMock()
        app.dependency_overrides[get_relational_pool] = lambda: mock_pool

        # Override get_settings to return a known API key
        mock_settings = MagicMock()
        mock_settings.api.get_api_key.return_value = "correct-key"

        with patch("container.get_settings", return_value=mock_settings):
            with TestClient(app) as client:
                response = client.get("/articles", headers={"X-API-Key": "wrong-key"})
                assert response.status_code == 403

    def test_articles_endpoint_with_valid_api_key_returns_200_or_503(self):
        """Test GET /articles with correct X-API-Key does not fail on auth (may fail on pool)."""
        from unittest.mock import AsyncMock, MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.dependencies import get_relational_pool
        from api.endpoints.articles import router

        app = FastAPI()
        app.include_router(router)

        # Properly mock the async pool session
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_count_result)

        mock_pool = MagicMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)
        app.dependency_overrides[get_relational_pool] = lambda: mock_pool

        mock_settings = MagicMock()
        mock_settings.api.get_api_key.return_value = "correct-key"

        with patch("container.get_settings", return_value=mock_settings):
            with TestClient(app) as client:
                response = client.get("/articles", headers={"X-API-Key": "correct-key"})
                # Should not be 401 or 403 — auth passed
                assert response.status_code not in (401, 403)

    def test_pipeline_trigger_without_api_key_returns_401(self):
        """Test POST /pipeline/trigger without X-API-Key returns 401."""
        from unittest.mock import MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.dependencies import get_cache_client, get_source_scheduler
        from api.endpoints.pipeline import router

        app = FastAPI()
        app.include_router(router)

        mock_cache = MagicMock()
        mock_scheduler = MagicMock()
        app.dependency_overrides[get_cache_client] = lambda: mock_cache
        app.dependency_overrides[get_source_scheduler] = lambda: mock_scheduler

        with TestClient(app) as client:
            response = client.post("/pipeline/trigger", json={})
            assert response.status_code == 401

    def test_pipeline_status_without_api_key_returns_401(self):
        """Test GET /pipeline/tasks/{task_id} without X-API-Key returns 401."""
        from unittest.mock import MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.dependencies import get_cache_client
        from api.endpoints.pipeline import router

        app = FastAPI()
        app.include_router(router)

        mock_cache = MagicMock()
        app.dependency_overrides[get_cache_client] = lambda: mock_cache

        with TestClient(app) as client:
            response = client.get(f"/pipeline/tasks/{uuid.uuid4()}")
            assert response.status_code == 401
