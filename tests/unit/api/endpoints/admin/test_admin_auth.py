# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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
    async def test_verify_admin_api_key_raises_503_when_not_configured_production(
        self,
    ) -> None:
        """Test verify_admin_api_key raises 503 when admin key not configured in production."""
        from api.middleware.auth import verify_admin_api_key

        regular_key = "regular-key-12345678901234567890123456"

        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = None  # Not configured
        mock_settings.api.get_api_key.return_value = regular_key

        with (
            patch("container.get_settings", return_value=mock_settings),
            patch.dict("os.environ", {"ENVIRONMENT": "production"}),
        ):
            # Admin key not configured: raises 503 Service Unavailable
            with pytest.raises(Exception) as exc_info:
                await verify_admin_api_key(key=regular_key)
            assert exc_info.value.status_code == 503
            assert "Admin API key not configured" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verify_admin_api_key_rejects_when_not_configured_development(
        self,
    ) -> None:
        """Test verify_admin_api_key raises 503 when admin key not configured even in dev."""
        from api.middleware.auth import verify_admin_api_key

        regular_key = "regular-key-12345678901234567890123456"

        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = None  # Not configured
        mock_settings.api.get_api_key.return_value = regular_key

        with (
            patch("container.get_settings", return_value=mock_settings),
            patch.dict("os.environ", {"ENVIRONMENT": "development"}),
        ):
            # Admin key not configured: rejects with 503 in all environments
            with pytest.raises(Exception) as exc_info:
                await verify_admin_api_key(key=regular_key)
            assert exc_info.value.status_code == 503
            assert "Admin API key not configured" in exc_info.value.detail


class TestAdminEndpointAuthorityUpdate:
    """Tests for PATCH /admin/authorities/{host} admin authentication."""

    def test_regular_api_key_cannot_update_authority(self) -> None:
        """Regular API key should receive 403 when calling PATCH /admin/authorities/{host}."""
        from api.endpoints.admin import router

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
                "api.endpoints.admin.admin._get_source_authority_repo",
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
        from api.endpoints.admin import router

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
        from api.endpoints.admin import router

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
                "api.endpoints.admin.admin._get_source_authority_repo",
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
        from api.endpoints.admin import router

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
        from api.endpoints.admin import router

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
        from api.dependencies import get_relational_pool_optional
        from api.endpoints.admin import router

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
        # deduplicate_articles() executes 4 statements (in order):
        #   1. SELECT COUNT(*) BEFORE  → scalar()
        #   2. DELETE                  → rowcount
        #   3. SELECT COUNT(*) AFTER   → scalar()  (only when rowcount == 0)
        #   4. SELECT COUNT(DISTINCT)  → scalar()
        # Plus a 5th safety slot in case DuckDB rowcount path differs.
        count_before_result = MagicMock()
        count_before_result.scalar = MagicMock(return_value=0)
        delete_result = MagicMock()
        delete_result.rowcount = 0  # triggers after-count branch
        count_after_result = MagicMock()
        count_after_result.scalar = MagicMock(return_value=0)
        kept_result = MagicMock()
        kept_result.scalar = MagicMock(return_value=0)
        async_session.execute = AsyncMock(
            side_effect=[
                count_before_result,
                delete_result,
                count_after_result,
                kept_result,
            ]
        )
        async_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=async_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_pool.session = MagicMock(return_value=mock_session)

        with patch("container.get_settings", return_value=mock_settings):
            app.dependency_overrides[get_relational_pool_optional] = lambda: mock_pool
            try:
                client = TestClient(app)
                response = client.post(
                    "/admin/articles/deduplicate",
                    headers={"X-API-Key": admin_key},
                )

                # Auth should pass (not 401/403)
                assert response.status_code not in [401, 403]
            finally:
                app.dependency_overrides.clear()


class TestAdminEndpointMemoryConsolidation:
    """Tests for POST /admin/memory/trigger-consolidation admin authentication."""

    def test_regular_api_key_cannot_trigger_consolidation(self) -> None:
        """Regular API key should receive 403 when calling POST /admin/memory/trigger-consolidation."""
        from api.endpoints.admin import router

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
        from api.endpoints.admin import router

        app = FastAPI()
        app.include_router(router)

        admin_key = "admin-key-123456789012345678901234567890"
        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = admin_key

        with patch("container.get_settings", return_value=mock_settings):
            client = TestClient(app)
            response = client.post("/admin/memory/trigger-consolidation")

            assert response.status_code == 401


class TestTriggerConsolidationBatchSizeValidation:
    """Regression tests for admin_046/admin_047: batch_size query param validation.

    FastAPI ``Query(10, ge=1, le=100)`` must reject:
    - ``batch_size=0`` (below ge=1) with 422
    - ``batch_size=invalid`` (non-int) with 422
    - ``batch_size=101`` (above le=100) with 422
    """

    @staticmethod
    def _make_client() -> TestClient:
        """Build a TestClient with admin router and mocked admin key.

        Overrides the ``_get_container`` dependency to avoid 503 from
        ``api.dependencies.get_container()`` (which raises 503 when the global
        container is not initialized). The 503 is raised during dependency
        resolution, which short-circuits FastAPI's Query parameter validation
        (``ge=1, le=100``). By mocking the container, Query validation runs
        normally and rejects invalid ``batch_size`` values with 422.
        """
        from api.endpoints.admin import router
        from api.endpoints.admin.admin import _get_container

        app = FastAPI()
        app.include_router(router)
        # Mock container so dependency resolution succeeds; Query validation
        # will reject invalid batch_size before the endpoint body runs.
        app.dependency_overrides[_get_container] = lambda: MagicMock(memory_service=None)

        admin_key = "admin-key-123456789012345678901234567890"
        mock_settings = MagicMock()
        mock_settings.api.admin_api_key = admin_key
        mock_settings.api.get_api_key.return_value = "regular-key-12345678901234567890123456"

        patcher = patch("container.get_settings", return_value=mock_settings)
        patcher.start()
        return TestClient(app)

    def test_batch_size_zero_rejected_with_422(self) -> None:
        """batch_size=0 SHALL be rejected with 422 (regression for admin_046)."""
        client = self._make_client()
        admin_key = "admin-key-123456789012345678901234567890"
        response = client.post(
            "/admin/memory/trigger-consolidation?batch_size=0",
            headers={"X-API-Key": admin_key},
        )
        assert response.status_code == 422

    def test_batch_size_non_int_rejected_with_422(self) -> None:
        """batch_size=invalid SHALL be rejected with 422 (regression for admin_047)."""
        client = self._make_client()
        admin_key = "admin-key-123456789012345678901234567890"
        response = client.post(
            "/admin/memory/trigger-consolidation?batch_size=invalid",
            headers={"X-API-Key": admin_key},
        )
        assert response.status_code == 422

    def test_batch_size_over_100_rejected_with_422(self) -> None:
        """batch_size=101 SHALL be rejected with 422 (le=100)."""
        client = self._make_client()
        admin_key = "admin-key-123456789012345678901234567890"
        response = client.post(
            "/admin/memory/trigger-consolidation?batch_size=101",
            headers={"X-API-Key": admin_key},
        )
        assert response.status_code == 422


class TestAdminEndpointRefreshAutoScores:
    """Tests for POST /admin/authorities/refresh-auto-scores admin authentication."""

    def test_regular_api_key_cannot_refresh_auto_scores(self) -> None:
        """Regular API key should receive 403 when calling POST /admin/authorities/refresh-auto-scores."""
        from api.endpoints.admin import router

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
        from api.endpoints.admin import router

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
        from api.dependencies import get_relational_pool_optional
        from api.endpoints.admin import router
        from api.endpoints.admin.admin import _get_container

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
        async_session.execute = AsyncMock(return_value=mock_hosts_result)
        mock_session.__aenter__ = AsyncMock(return_value=async_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_pool.session = MagicMock(return_value=mock_session)

        mock_repo = MagicMock()
        mock_repo.update_auto_score = AsyncMock()

        mock_container = MagicMock()
        mock_container.source_authority_repo.return_value = mock_repo

        with patch("container.get_settings", return_value=mock_settings):
            app.dependency_overrides[get_relational_pool_optional] = lambda: mock_pool
            app.dependency_overrides[_get_container] = lambda: mock_container
            try:
                client = TestClient(app)
                response = client.post(
                    "/admin/authorities/refresh-auto-scores",
                    headers={"X-API-Key": admin_key},
                )

                # Auth should pass (not 401/403)
                assert response.status_code not in [401, 403]
            finally:
                app.dependency_overrides.clear()


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
