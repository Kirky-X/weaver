# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for expanded audit logging coverage.

TDD Phase 1: Write tests first, then implement.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Mock setfit before any imports that trigger the chain
if "setfit" not in sys.modules:
    sys.modules["setfit"] = MagicMock()
    sys.modules["setfit.span"] = MagicMock()
    sys.modules["setfit.span.trainer"] = MagicMock()

import pytest


class TestAuditServiceInjection:
    """Test AuditLogService injection into middleware."""

    def test_audit_service_injection(self) -> None:
        """AuditLogService should be injectable into middleware."""
        from api.middleware.audit import AuditLogMiddleware

        mock_app = MagicMock()
        mock_service = MagicMock()
        middleware = AuditLogMiddleware(
            app=mock_app,
            audit_service=mock_service,
        )
        assert middleware._audit_service is mock_service

    def test_audit_service_none_by_default(self) -> None:
        """Without injection, audit_service should be None."""
        from api.middleware.audit import AuditLogMiddleware

        mock_app = MagicMock()
        middleware = AuditLogMiddleware(app=mock_app)
        assert middleware._audit_service is None


class TestAuditPathConfiguration:
    """Test configurable audit path patterns."""

    def test_default_audited_paths(self) -> None:
        """Default audited_paths should include /api/v1/admin."""
        from api.middleware.audit import AuditLogMiddleware

        middleware = AuditLogMiddleware(app=MagicMock())
        assert "/api/v1/admin" in middleware._audited_paths

    def test_default_write_only_paths(self) -> None:
        """Default write_only_paths should include pipeline, content, graph."""
        from api.middleware.audit import AuditLogMiddleware

        middleware = AuditLogMiddleware(app=MagicMock())
        assert "/api/v1/pipeline" in middleware._write_only_paths
        assert "/api/v1/content" in middleware._write_only_paths
        assert "/api/v1/graph" in middleware._write_only_paths

    def test_custom_audited_paths(self) -> None:
        """Custom audited_paths should override defaults."""
        from api.middleware.audit import AuditLogMiddleware

        middleware = AuditLogMiddleware(
            app=MagicMock(),
            audited_paths=["/api/v1/custom"],
        )
        assert middleware._audited_paths == ["/api/v1/custom"]


class TestShouldAudit:
    """Test _should_audit() method."""

    def test_admin_path_all_methods(self) -> None:
        """Admin paths should be audited for all methods."""
        from api.middleware.audit import AuditLogMiddleware

        middleware = AuditLogMiddleware(app=MagicMock())
        for method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
            assert middleware._should_audit("/api/v1/admin/users", method) is True

    def test_pipeline_write_operation(self) -> None:
        """Pipeline POST should be audited."""
        from api.middleware.audit import AuditLogMiddleware

        middleware = AuditLogMiddleware(app=MagicMock())
        assert middleware._should_audit("/api/v1/pipeline/url", "POST") is True

    def test_content_write_operation(self) -> None:
        """Content PUT should be audited."""
        from api.middleware.audit import AuditLogMiddleware

        middleware = AuditLogMiddleware(app=MagicMock())
        assert middleware._should_audit("/api/v1/content/123", "PUT") is True

    def test_graph_write_operation(self) -> None:
        """Graph DELETE should be audited."""
        from api.middleware.audit import AuditLogMiddleware

        middleware = AuditLogMiddleware(app=MagicMock())
        assert middleware._should_audit("/api/v1/graph/nodes", "DELETE") is True

    def test_read_operation_not_audited_for_write_paths(self) -> None:
        """GET requests to write-only paths should not be audited."""
        from api.middleware.audit import AuditLogMiddleware

        middleware = AuditLogMiddleware(app=MagicMock())
        assert middleware._should_audit("/api/v1/pipeline/status", "GET") is False
        assert middleware._should_audit("/api/v1/content/search", "GET") is False

    def test_unrelated_path_not_audited(self) -> None:
        """Unrelated paths should not be audited."""
        from api.middleware.audit import AuditLogMiddleware

        middleware = AuditLogMiddleware(app=MagicMock())
        assert middleware._should_audit("/api/v1/search", "POST") is False
        assert middleware._should_audit("/health", "GET") is False
