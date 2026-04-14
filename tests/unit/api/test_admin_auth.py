# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for admin API key authentication.

This module tests the admin permission upgrade for 4 write operation endpoints:
1. PATCH /admin/authorities/{host} - Update source authority
2. POST /admin/articles/deduplicate - Remove duplicate articles
3. POST /admin/memory/trigger-consolidation - Trigger memory consolidation
4. POST /admin/authorities/refresh-auto-scores - Refresh auto scores

Tests verify:
- Regular API key cannot access admin endpoints (403 Forbidden)
- Admin API key can access admin endpoints (200 OK)
- Missing API key is rejected (401 Unauthorized)
- Proper error messages are returned

Note: These tests use FastAPI TestClient with mocked dependencies to avoid
requiring a real database.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestAdminAuthMiddleware:
    """Tests for admin API key authentication middleware."""

    @pytest.mark.asyncio
    async def test_verify_admin_api_key_missing_key_returns_401(self) -> None:
        """Test verify_admin_api_key raises 401 when key is missing."""
        from api.middleware.auth import verify_admin_api_key

        with pytest.raises(Exception) as exc_info:
            await verify_admin_api_key(key=None)
        assert exc_info.value.status_code == 401
        assert "Missing API key" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verify_admin_api_key_invalid_key_returns_403(self) -> None:
        """Test verify_admin_api_key raises 403 for invalid key."""
        from api.middleware.auth import verify_admin_api_key

        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = "admin-key-123456789012345678901234567890"
        mock_settings.api.get_api_key.return_value = "regular-key-12345678901234567890123456"

        with patch("container.get_settings", return_value=mock_settings):
            with pytest.raises(Exception) as exc_info:
                await verify_admin_api_key(key="invalid-key")
            assert exc_info.value.status_code == 403
            assert "Invalid API Key" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verify_admin_api_key_valid_admin_key_succeeds(self) -> None:
        """Test verify_admin_api_key accepts valid admin key."""
        from api.middleware.auth import verify_admin_api_key

        admin_key = "admin-key-123456789012345678901234567890"
        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = admin_key
        mock_settings.api.get_api_key.return_value = "regular-key-12345678901234567890123456"

        with patch("container.get_settings", return_value=mock_settings):
            result = await verify_admin_api_key(key=admin_key)
            assert result == admin_key

    @pytest.mark.asyncio
    async def test_verify_admin_api_key_regular_key_returns_403(self) -> None:
        """Test verify_admin_api_key rejects regular API key with admin-specific error."""
        from api.middleware.auth import verify_admin_api_key

        admin_key = "admin-key-123456789012345678901234567890"
        regular_key = "regular-key-12345678901234567890123456"

        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = admin_key
        mock_settings.api.get_api_key.return_value = regular_key

        with patch("container.get_settings", return_value=mock_settings):
            with pytest.raises(Exception) as exc_info:
                await verify_admin_api_key(key=regular_key)
            assert exc_info.value.status_code == 403
            assert "Admin access required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verify_admin_api_key_fallback_when_not_configured(self) -> None:
        """Test verify_admin_api_key falls back to regular key when admin key not configured."""
        from api.middleware.auth import verify_admin_api_key

        regular_key = "regular-key-12345678901234567890123456"

        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = None  # Not configured
        mock_settings.api.get_api_key.return_value = regular_key

        with (
            patch("container.get_settings", return_value=mock_settings),
            patch.dict("os.environ", {"ENVIRONMENT": "development"}),
        ):
            # In development, regular key should work as admin key fallback
            result = await verify_admin_api_key(key=regular_key)
            assert result == regular_key


class TestAdminEndpointAuthorityUpdate:
    """Tests for PATCH /admin/authorities/{host} admin authentication."""

    def test_regular_api_key_cannot_update_authority(self) -> None:
        """Regular API key should receive 403 when calling PATCH /admin/authorities/{host}."""
        from api.endpoints.admin.admin import router

        app = FastAPI()
        app.include_router(router)

        admin_key = "admin-key-123456789012345678901234567890"
        regular_key = "regular-key-12345678901234567890123456"

        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = admin_key
        mock_settings.api.get_api_key.return_value = regular_key

        mock_repo = MagicMock()
        mock_repo.update_authority = AsyncMock(
            return_value={"host": "example.com", "authority": 0.8}
        )

        with (
            patch("container.get_settings", return_value=mock_settings),
            patch(
                "api.endpoints.admin.admin.get_source_authority_repo",
                return_value=mock_repo,
            ),
        ):
            client = TestClient(app)
            response = client.patch(
                "/admin/authorities/example.com",
                json={"authority": 0.8},
                headers={"X-API-Key": regular_key},
            )

            assert response.status_code == 403
            assert "Admin access required" in response.json()["detail"]

    def test_no_api_key_rejected_for_authority_update(self) -> None:
        """Missing API key should receive 401 when calling PATCH /admin/authorities/{host}."""
        from api.endpoints.admin.admin import router

        app = FastAPI()
        app.include_router(router)

        admin_key = "admin-key-123456789012345678901234567890"
        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = admin_key
        mock_settings.api.get_api_key.return_value = "regular-key"

        with patch("container.get_settings", return_value=mock_settings):
            client = TestClient(app)
            response = client.patch(
                "/admin/authorities/example.com",
                json={"authority": 0.8},
            )

            assert response.status_code == 401

    def test_admin_api_key_can_update_authority(self) -> None:
        """Admin API key should successfully call PATCH /admin/authorities/{host}."""
        from api.endpoints.admin.admin import router

        app = FastAPI()
        app.include_router(router)

        admin_key = "admin-key-123456789012345678901234567890"
        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = admin_key
        mock_settings.api.get_api_key.return_value = "regular-key"

        mock_repo = MagicMock()
        mock_repo.update_authority = MagicMock(
            return_value={"host": "example.com", "authority": 0.8}
        )

        with (
            patch("container.get_settings", return_value=mock_settings),
            patch(
                "api.endpoints.admin.admin.get_source_authority_repo",
                return_value=mock_repo,
            ),
        ):
            client = TestClient(app)
            response = client.patch(
                "/admin/authorities/example.com",
                json={"authority": 0.8},
                headers={"X-API-Key": admin_key},
            )

            # Auth should pass (200) or fail on DB (500/503), but not auth error (401/403)
            assert response.status_code not in [401, 403]


class TestAdminEndpointDeduplicate:
    """Tests for POST /admin/articles/deduplicate admin authentication."""

    def test_regular_api_key_cannot_deduplicate(self) -> None:
        """Regular API key should receive 403 when calling POST /admin/articles/deduplicate."""
        from api.endpoints.admin.admin import router

        app = FastAPI()
        app.include_router(router)

        admin_key = "admin-key-123456789012345678901234567890"
        regular_key = "regular-key-12345678901234567890123456"

        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = admin_key
        mock_settings.api.get_api_key.return_value = regular_key

        with patch("container.get_settings", return_value=mock_settings):
            client = TestClient(app)
            response = client.post(
                "/admin/articles/deduplicate",
                headers={"X-API-Key": regular_key},
            )

            assert response.status_code == 403
            assert "Admin access required" in response.json()["detail"]

    def test_no_api_key_rejected_for_deduplicate(self) -> None:
        """Missing API key should receive 401 when calling POST /admin/articles/deduplicate."""
        from api.endpoints.admin.admin import router

        app = FastAPI()
        app.include_router(router)

        admin_key = "admin-key-123456789012345678901234567890"
        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = admin_key

        with patch("container.get_settings", return_value=mock_settings):
            client = TestClient(app)
            response = client.post("/admin/articles/deduplicate")

            assert response.status_code == 401

    def test_admin_api_key_can_deduplicate(self) -> None:
        """Admin API key should successfully call POST /admin/articles/deduplicate."""
        from api.endpoints.admin.admin import router

        app = FastAPI()
        app.include_router(router)

        admin_key = "admin-key-123456789012345678901234567890"
        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = admin_key
        mock_settings.api.get_api_key.return_value = "regular-key"

        # Mock database pool
        mock_pool = MagicMock()
        mock_session = MagicMock()

        # Make session work as async context manager
        async_session = MagicMock()
        async_session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        async_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=async_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_pool.session = MagicMock(return_value=mock_session)

        with (
            patch("container.get_settings", return_value=mock_settings),
            patch(
                "api.endpoints._deps.Endpoints.get_relational_pool_optional",
                return_value=mock_pool,
            ),
        ):
            client = TestClient(app)
            response = client.post(
                "/admin/articles/deduplicate",
                headers={"X-API-Key": admin_key},
            )

            # Auth should pass (not 401/403)
            assert response.status_code not in [401, 403]


class TestAdminEndpointMemoryConsolidation:
    """Tests for POST /admin/memory/trigger-consolidation admin authentication."""

    def test_regular_api_key_cannot_trigger_consolidation(self) -> None:
        """Regular API key should receive 403 when calling POST /admin/memory/trigger-consolidation."""
        from api.endpoints.admin.admin import router

        app = FastAPI()
        app.include_router(router)

        admin_key = "admin-key-123456789012345678901234567890"
        regular_key = "regular-key-12345678901234567890123456"

        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = admin_key
        mock_settings.api.get_api_key.return_value = regular_key

        with patch("container.get_settings", return_value=mock_settings):
            client = TestClient(app)
            response = client.post(
                "/admin/memory/trigger-consolidation",
                headers={"X-API-Key": regular_key},
            )

            assert response.status_code == 403
            assert "Admin access required" in response.json()["detail"]

    def test_no_api_key_rejected_for_consolidation(self) -> None:
        """Missing API key should receive 401 when calling POST /admin/memory/trigger-consolidation."""
        from api.endpoints.admin.admin import router

        app = FastAPI()
        app.include_router(router)

        admin_key = "admin-key-123456789012345678901234567890"
        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = admin_key

        with patch("container.get_settings", return_value=mock_settings):
            client = TestClient(app)
            response = client.post("/admin/memory/trigger-consolidation")

            assert response.status_code == 401


class TestAdminEndpointRefreshAutoScores:
    """Tests for POST /admin/authorities/refresh-auto-scores admin authentication."""

    def test_regular_api_key_cannot_refresh_auto_scores(self) -> None:
        """Regular API key should receive 403 when calling POST /admin/authorities/refresh-auto-scores."""
        from api.endpoints.admin.admin import router

        app = FastAPI()
        app.include_router(router)

        admin_key = "admin-key-123456789012345678901234567890"
        regular_key = "regular-key-12345678901234567890123456"

        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = admin_key
        mock_settings.api.get_api_key.return_value = regular_key

        with patch("container.get_settings", return_value=mock_settings):
            client = TestClient(app)
            response = client.post(
                "/admin/authorities/refresh-auto-scores",
                headers={"X-API-Key": regular_key},
            )

            assert response.status_code == 403
            assert "Admin access required" in response.json()["detail"]

    def test_no_api_key_rejected_for_refresh_auto_scores(self) -> None:
        """Missing API key should receive 401 when calling POST /admin/authorities/refresh-auto-scores."""
        from api.endpoints.admin.admin import router

        app = FastAPI()
        app.include_router(router)

        admin_key = "admin-key-123456789012345678901234567890"
        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = admin_key

        with patch("container.get_settings", return_value=mock_settings):
            client = TestClient(app)
            response = client.post("/admin/authorities/refresh-auto-scores")

            assert response.status_code == 401

    def test_admin_api_key_can_refresh_auto_scores(self) -> None:
        """Admin API key should successfully call POST /admin/authorities/refresh-auto-scores."""
        from api.endpoints.admin.admin import router

        app = FastAPI()
        app.include_router(router)

        admin_key = "admin-key-123456789012345678901234567890"
        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = admin_key
        mock_settings.api.get_api_key.return_value = "regular-key"

        # Mock database pool and repo
        mock_pool = MagicMock()
        mock_session = MagicMock()

        # Mock session for async context manager
        async_session = MagicMock()
        # First execute call returns hosts
        mock_hosts_result = MagicMock()
        mock_hosts_result.__iter__ = MagicMock(return_value=iter([]))
        async_session.execute = MagicMock(return_value=mock_hosts_result)
        mock_session.__aenter__ = AsyncMock(return_value=async_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_pool.session = MagicMock(return_value=mock_session)

        mock_repo = MagicMock()
        mock_repo.update_auto_score = AsyncMock()

        mock_container = MagicMock()
        mock_container.source_authority_repo.return_value = mock_repo

        with (
            patch("container.get_settings", return_value=mock_settings),
            patch("api.endpoints.admin.admin.get_container", return_value=mock_container),
            patch(
                "api.endpoints._deps.Endpoints.get_relational_pool_optional",
                return_value=mock_pool,
            ),
        ):
            client = TestClient(app)
            response = client.post(
                "/admin/authorities/refresh-auto-scores",
                headers={"X-API-Key": admin_key},
            )

            # Auth should pass (not 401/403)
            assert response.status_code not in [401, 403]


class TestAdminAuthErrorMessages:
    """Tests for admin authentication error message quality."""

    @pytest.mark.asyncio
    async def test_missing_key_error_message_is_clear(self) -> None:
        """Error message for missing key should be clear and actionable."""
        from api.middleware.auth import verify_admin_api_key

        with pytest.raises(Exception) as exc_info:
            await verify_admin_api_key(key=None)
        assert "Missing API key" in exc_info.value.detail
        assert "X-API-Key" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_regular_key_error_message_identifies_admin_requirement(self) -> None:
        """Error message for regular key should identify admin requirement."""
        from api.middleware.auth import verify_admin_api_key

        admin_key = "admin-key-123456789012345678901234567890"
        regular_key = "regular-key-12345678901234567890123456"

        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = admin_key
        mock_settings.api.get_api_key.return_value = regular_key

        with patch("container.get_settings", return_value=mock_settings):
            with pytest.raises(Exception) as exc_info:
                await verify_admin_api_key(key=regular_key)
            assert "Admin access required" in exc_info.value.detail
            assert "Regular API key not authorized" in exc_info.value.detail
