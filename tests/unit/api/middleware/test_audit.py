# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for audit logging middleware."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middleware.audit import AuditLogMiddleware


class TestAuditLogMiddleware:
    """Tests for audit logging middleware."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.app = FastAPI()
        self.app.add_middleware(AuditLogMiddleware)

        @self.app.get("/api/v1/admin/articles")
        async def list_articles() -> dict:
            return {"articles": []}

        @self.app.get("/api/v1/admin/articles/{article_id}")
        async def get_article(article_id: str) -> dict:
            return {"id": article_id}

        @self.app.post("/api/v1/admin/articles")
        async def create_article(data: dict) -> dict:
            return {"created": True}

        @self.app.get("/api/v1/status")
        async def status() -> dict:
            return {"status": "ok"}

        @self.app.get("/health")
        async def health() -> dict:
            return {"status": "healthy"}

        self.client = TestClient(self.app)

    @patch("api.middleware.audit.log")
    def test_admin_endpoint_logs_success(self, mock_log: MagicMock) -> None:
        """Test that successful admin endpoint requests are logged."""
        response = self.client.get(
            "/api/v1/admin/articles",
            headers={"Authorization": "Bearer test-api-key-12345678"},
        )

        assert response.status_code == 200

        # Verify audit log was called
        mock_log.info.assert_called_once()
        call_args = mock_log.info.call_args

        assert call_args[0][0] == "audit_log"
        assert call_args[1]["action"] == "GET:/api/v1/admin/articles"
        assert call_args[1]["target_type"] == "articles"
        assert call_args[1]["target_id"] is None
        assert call_args[1]["status_code"] == 200
        assert "duration_ms" in call_args[1]

    @patch("api.middleware.audit.log")
    def test_admin_endpoint_with_id_logs_correctly(self, mock_log: MagicMock) -> None:
        """Test that admin endpoint with ID logs correctly."""
        response = self.client.get(
            "/api/v1/admin/articles/123",
            headers={"Authorization": "Bearer test-api-key-12345678"},
        )

        assert response.status_code == 200

        # Verify audit log was called
        mock_log.info.assert_called_once()
        call_args = mock_log.info.call_args

        assert call_args[1]["action"] == "GET:/api/v1/admin/articles/123"
        assert call_args[1]["target_type"] == "articles"
        assert call_args[1]["target_id"] == "123"

    @patch("api.middleware.audit.log")
    def test_non_admin_endpoint_not_logged(self, mock_log: MagicMock) -> None:
        """Test that non-admin endpoints are not logged."""
        response = self.client.get("/api/v1/status")

        assert response.status_code == 200

        # Verify audit log was NOT called
        mock_log.info.assert_not_called()

    @patch("api.middleware.audit.log")
    def test_health_endpoint_not_logged(self, mock_log: MagicMock) -> None:
        """Test that health endpoint is not logged."""
        response = self.client.get("/health")

        assert response.status_code == 200

        # Verify audit log was NOT called
        mock_log.info.assert_not_called()

    @patch("api.middleware.audit.log")
    def test_failed_request_is_logged(self, mock_log: MagicMock) -> None:
        """Test that failed requests (4xx/5xx) are also logged for security audit."""

        # Create a failing endpoint
        @self.app.get("/api/v1/admin/error")
        async def error_endpoint() -> dict:
            from fastapi import HTTPException

            raise HTTPException(status_code=500, detail="Internal error")

        response = self.client.get(
            "/api/v1/admin/error",
            headers={"Authorization": "Bearer test-api-key-12345678"},
        )

        assert response.status_code == 500

        # Verify audit log WAS called (failed requests must be recorded)
        mock_log.info.assert_called_once()
        call_args = mock_log.info.call_args
        assert call_args[1]["status_code"] == 500

    @patch("api.middleware.audit.log")
    def test_unauthorized_request_is_logged(self, mock_log: MagicMock) -> None:
        """Test that 401 unauthorized requests are logged for security audit."""

        @self.app.get("/api/v1/admin/protected")
        async def protected_endpoint() -> dict:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Unauthorized")

        response = self.client.get("/api/v1/admin/protected")

        assert response.status_code == 401

        # Verify audit log WAS called
        mock_log.info.assert_called_once()
        call_args = mock_log.info.call_args
        assert call_args[1]["status_code"] == 401

    @patch("api.middleware.audit.log")
    def test_client_ip_logged(self, mock_log: MagicMock) -> None:
        """Test that client IP is logged."""
        response = self.client.get(
            "/api/v1/admin/articles",
            headers={"Authorization": "Bearer test-api-key-12345678"},
        )

        assert response.status_code == 200

        # Verify client IP is in log
        call_args = mock_log.info.call_args
        assert "client_ip" in call_args[1]

    @patch("api.middleware.audit.log")
    def test_api_key_id_extracted_from_bearer(self, mock_log: MagicMock) -> None:
        """Test that API key ID is extracted from Bearer token."""
        response = self.client.get(
            "/api/v1/admin/articles",
            headers={"Authorization": "Bearer test-api-key-12345678"},
        )

        assert response.status_code == 200

        # Verify key ID is extracted
        call_args = mock_log.info.call_args
        assert call_args[1]["key_id"] == "test-api..."

    @patch("api.middleware.audit.log")
    def test_anonymous_when_no_auth(self, mock_log: MagicMock) -> None:
        """Test that anonymous is used when no auth header."""
        response = self.client.get("/api/v1/admin/articles")

        assert response.status_code == 200

        # Verify key ID is anonymous
        call_args = mock_log.info.call_args
        assert call_args[1]["key_id"] == "anonymous"

    @patch("api.middleware.audit.log")
    def test_query_params_logged(self, mock_log: MagicMock) -> None:
        """Test that query parameters are logged."""
        response = self.client.get(
            "/api/v1/admin/articles?page=1&limit=10",
            headers={"Authorization": "Bearer test-api-key-12345678"},
        )

        assert response.status_code == 200

        # Verify query params are in detail
        call_args = mock_log.info.call_args
        detail = call_args[1]["detail"]
        assert detail["query_params"]["page"] == "1"
        assert detail["query_params"]["limit"] == "10"

    @patch("api.middleware.audit.log")
    def test_duration_logged(self, mock_log: MagicMock) -> None:
        """Test that request duration is logged."""
        response = self.client.get(
            "/api/v1/admin/articles",
            headers={"Authorization": "Bearer test-api-key-12345678"},
        )

        assert response.status_code == 200

        # Verify duration is logged
        call_args = mock_log.info.call_args
        assert "duration_ms" in call_args[1]
        assert call_args[1]["duration_ms"] >= 0

    @patch("api.middleware.audit.log")
    def test_audit_log_error_doesnt_break_request(self, mock_log: MagicMock) -> None:
        """Test that audit logging errors don't break the request."""
        # Make the logger raise an exception
        mock_log.info.side_effect = Exception("Logging failed")

        response = self.client.get(
            "/api/v1/admin/articles",
            headers={"Authorization": "Bearer test-api-key-12345678"},
        )

        # Request should still succeed
        assert response.status_code == 200

        # Error should be logged
        mock_log.error.assert_called_once()
        error_call_args = mock_log.error.call_args
        assert error_call_args[0][0] == "audit_log_failed"


class TestAuditLogMiddlewareConfiguration:
    """Tests for middleware configuration."""

    def test_middleware_with_custom_admin_prefix(self) -> None:
        """Test middleware behavior with different admin prefix."""
        # The middleware uses ADMIN_PREFIX constant
        # This test verifies the prefix is respected
        app = FastAPI()
        app.add_middleware(AuditLogMiddleware)

        @app.get("/api/v1/admin/test")
        async def admin_test() -> dict:
            return {"test": True}

        @app.get("/api/v2/admin/test")
        async def admin_v2_test() -> dict:
            return {"test": True}

        client = TestClient(app)

        with patch("api.middleware.audit.log") as mock_log:
            # v1 admin should be logged
            response = client.get("/api/v1/admin/test")
            assert response.status_code == 200
            mock_log.info.assert_called_once()

            mock_log.reset_mock()

            # v2 admin should NOT be logged (different prefix)
            response = client.get("/api/v2/admin/test")
            assert response.status_code == 200
            mock_log.info.assert_not_called()

    def test_middleware_with_sub_admin_paths(self) -> None:
        """Test middleware with nested admin paths."""
        app = FastAPI()
        app.add_middleware(AuditLogMiddleware)

        @app.get("/api/v1/admin/communities/123/members")
        async def community_members() -> dict:
            return {"members": []}

        client = TestClient(app)

        with patch("api.middleware.audit.log") as mock_log:
            response = client.get("/api/v1/admin/communities/123/members")
            assert response.status_code == 200

            call_args = mock_log.info.call_args
            assert call_args[1]["target_type"] == "communities"
            assert call_args[1]["target_id"] == "123"
