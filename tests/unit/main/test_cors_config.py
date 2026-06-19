# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for CORS configuration.

This module tests the environment-aware CORS configuration:
- Development environment: allows multiple origins with credentials
- Production environment with single origin: allows credentials
- Production environment with multiple origins: truncates to first + WARNING
- Production environment with no CORS_ORIGINS: disables CORS + WARNING
- OPTIONS preflight requests are handled correctly

Tests verify:
- CORS origins are correctly set based on environment
- CORS middleware is properly configured
- WARNING logs are generated when appropriate
- Preflight requests return correct headers
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient


def _make_mock_settings() -> MagicMock:
    """Create mock Settings with attributes needed for create_app()."""
    settings = MagicMock()
    settings.traffic_anomaly = MagicMock(enabled=False)
    settings.api.hmac_signing_enabled = False
    return settings


class TestCORSDevelopmentEnvironment:
    """Tests for CORS configuration in development environment."""

    def test_development_allows_multiple_origins(self) -> None:
        """Development environment should allow multiple CORS origins."""
        with (
            patch("main._ensure_spacy_models"),
            patch.dict("os.environ", {"ENVIRONMENT": "development"}, clear=False),
        ):
            # Remove production-specific env vars
            env_vars = {"ENVIRONMENT": "development"}
            if "CORS_ORIGINS" in __import__("os").environ:
                del __import__("os").environ["CORS_ORIGINS"]

            with patch.dict("os.environ", env_vars, clear=False):
                from main import create_app

                mock_settings = _make_mock_settings()
                with patch("main.Settings", return_value=mock_settings):
                    app = create_app()

                    # Verify CORS middleware is present
                    cors_middleware = None
                    for middleware in app.user_middleware:
                        if middleware.cls == CORSMiddleware:
                            cors_middleware = middleware
                            break

                    assert cors_middleware is not None, "CORS middleware should be present"

                    # Check origins include defaults
                    origins = cors_middleware.kwargs.get("allow_origins", [])
                    assert len(origins) > 1, "Development should allow multiple origins"
                    assert any("localhost" in origin for origin in origins)

    def test_development_allows_credentials(self) -> None:
        """Development environment should allow credentials."""
        with (
            patch("main._ensure_spacy_models"),
            patch.dict("os.environ", {"ENVIRONMENT": "development"}),
        ):
            from main import create_app

            mock_settings = _make_mock_settings()
            with patch("main.Settings", return_value=mock_settings):
                app = create_app()

                # Find CORS middleware
                for middleware in app.user_middleware:
                    if middleware.cls == CORSMiddleware:
                        allow_credentials = middleware.kwargs.get("allow_credentials", False)
                        assert allow_credentials is True, "Development should allow credentials"
                        break

    def test_development_custom_origins(self) -> None:
        """Development environment should respect custom CORS_ORIGINS."""
        custom_origins = "http://custom1.com,http://custom2.com,http://custom3.com"

        with (
            patch("main._ensure_spacy_models"),
            patch.dict(
                "os.environ", {"ENVIRONMENT": "development", "CORS_ORIGINS": custom_origins}
            ),
        ):
            from main import create_app

            mock_settings = _make_mock_settings()
            with patch("main.Settings", return_value=mock_settings):
                app = create_app()

                # Find CORS middleware
                for middleware in app.user_middleware:
                    if middleware.cls == CORSMiddleware:
                        origins = middleware.kwargs.get("allow_origins", [])
                        assert "http://custom1.com" in origins
                        assert "http://custom2.com" in origins
                        assert "http://custom3.com" in origins
                        break


class TestCORSProductionEnvironment:
    """Tests for CORS configuration in production environment."""

    def test_production_single_origin_with_credentials(
        self,
    ) -> None:
        """Production with single origin should allow credentials and not warn."""
        with (
            patch("main._ensure_spacy_models"),
            patch.dict(
                "os.environ",
                {"ENVIRONMENT": "production", "CORS_ORIGINS": "https://app.example.com"},
            ),
        ):
            from api.middleware.setup import log
            from main import create_app

            mock_settings = _make_mock_settings()
            with patch("main.Settings", return_value=mock_settings):
                with patch.object(log, "warning") as mock_warning:
                    app = create_app()

                # Find CORS middleware
                cors_found = False
                for middleware in app.user_middleware:
                    if middleware.cls == CORSMiddleware:
                        cors_found = True
                        origins = middleware.kwargs.get("allow_origins", [])
                        allow_credentials = middleware.kwargs.get("allow_credentials", False)

                        assert len(origins) == 1
                        assert origins[0] == "https://app.example.com"
                        assert allow_credentials is True

                assert cors_found, "CORS middleware should be present"

                # Should NOT generate warning for single origin
                cors_warnings = [
                    call for call in mock_warning.call_args_list if "cors_" in str(call).lower()
                ]
                assert len(cors_warnings) == 0

    def test_production_multiple_origins_truncates_and_warns(
        self,
    ) -> None:
        """Production with multiple origins should truncate to first and log WARNING."""
        with (
            patch("main._ensure_spacy_models"),
            patch.dict(
                "os.environ",
                {
                    "ENVIRONMENT": "production",
                    "CORS_ORIGINS": (
                        "https://app1.example.com,https://app2.example.com,https://app3.example.com"
                    ),
                },
            ),
        ):
            from api.middleware.setup import log
            from main import create_app

            mock_settings = _make_mock_settings()
            mock_settings.environment = "production"
            with patch("main.Settings", return_value=mock_settings):
                with patch.object(log, "warning") as mock_warning:
                    app = create_app()

                # Find CORS middleware
                for middleware in app.user_middleware:
                    if middleware.cls == CORSMiddleware:
                        origins = middleware.kwargs.get("allow_origins", [])

                        # Should only have first origin
                        assert len(origins) == 1
                        assert origins[0] == "https://app1.example.com"
                        break

                # Should generate WARNING about truncation
                mock_warning.assert_called()
                # Check that one of the calls contains the expected message
                call_args = [str(call) for call in mock_warning.call_args_list]
                assert any("Multiple CORS origins" in arg for arg in call_args)

    def test_production_no_origins_disables_cors_and_warns(
        self,
    ) -> None:
        """Production with no CORS_ORIGINS should disable CORS and log WARNING."""
        with (
            patch("main._ensure_spacy_models"),
            patch.dict("os.environ", {"ENVIRONMENT": "production", "CORS_ORIGINS": ""}),
        ):
            from api.middleware.setup import log
            from main import create_app

            mock_settings = _make_mock_settings()
            mock_settings.environment = "production"
            # Mock log.warning to track calls
            with patch("main.Settings", return_value=mock_settings):
                with patch.object(log, "warning") as mock_warning:
                    app = create_app()

                # Find CORS middleware
                for middleware in app.user_middleware:
                    if middleware.cls == CORSMiddleware:
                        origins = middleware.kwargs.get("allow_origins", [])
                        allow_credentials = middleware.kwargs.get("allow_credentials", False)

                        # Should have empty origins
                        assert len(origins) == 0
                        assert allow_credentials is False

                # Should generate WARNING about disabled CORS
                mock_warning.assert_called()
                # Check that one of the calls contains the expected message
                call_args = [str(call) for call in mock_warning.call_args_list]
                assert any("CORS_ORIGINS not set" in arg for arg in call_args)


class TestCORSPreflightRequests:
    """Tests for CORS preflight (OPTIONS) request handling."""

    def test_preflight_request_development(self) -> None:
        """OPTIONS preflight request should work in development."""
        with (
            patch("main._ensure_spacy_models"),
            patch.dict("os.environ", {"ENVIRONMENT": "development"}),
        ):
            from main import create_app

            mock_settings = _make_mock_settings()
            with patch("main.Settings", return_value=mock_settings):
                app = create_app()
                client = TestClient(app)

                # Send preflight request
                response = client.options(
                    "/api/v1/health",
                    headers={
                        "Origin": "http://localhost:3000",
                        "Access-Control-Request-Method": "GET",
                        "Access-Control-Request-Headers": "X-API-Key",
                    },
                )

                # Should succeed (200 or 204)
                assert response.status_code in [200, 204]

                # Check CORS headers
                assert "access-control-allow-origin" in response.headers
                assert (
                    response.headers["access-control-allow-origin"] == "http://localhost:3000"
                    or response.headers["access-control-allow-origin"] == "*"
                )

    def test_preflight_request_production_single_origin(self) -> None:
        """OPTIONS preflight request should work in production with single origin."""
        with (
            patch("main._ensure_spacy_models"),
            patch.dict(
                "os.environ",
                {"ENVIRONMENT": "production", "CORS_ORIGINS": "https://app.example.com"},
            ),
        ):
            from main import create_app

            mock_settings = _make_mock_settings()
            with patch("main.Settings", return_value=mock_settings):
                app = create_app()
                client = TestClient(app)

                # Send preflight request
                response = client.options(
                    "/api/v1/health",
                    headers={
                        "Origin": "https://app.example.com",
                        "Access-Control-Request-Method": "GET",
                    },
                )

                # Should succeed
                assert response.status_code in [200, 204]

                # Check CORS headers
                assert "access-control-allow-origin" in response.headers

    def test_preflight_request_production_no_origins(self) -> None:
        """OPTIONS preflight request should not include CORS headers when disabled."""
        with (
            patch("main._ensure_spacy_models"),
            patch.dict("os.environ", {"ENVIRONMENT": "production", "CORS_ORIGINS": ""}),
        ):
            from main import create_app

            mock_settings = _make_mock_settings()
            with patch("main.Settings", return_value=mock_settings):
                app = create_app()
                client = TestClient(app)

                # Send preflight request
                response = client.options(
                    "/api/v1/health",
                    headers={
                        "Origin": "https://app.example.com",
                        "Access-Control-Request-Method": "GET",
                    },
                )

                # When CORS is disabled, OPTIONS may fail - that's acceptable
                # The important thing is no CORS headers are present
                if response.status_code in [200, 204]:
                    # If it succeeds, ensure no CORS headers
                    assert "access-control-allow-origin" not in response.headers
                else:
                    # If it fails (400), that's also acceptable for disabled CORS
                    assert response.status_code == 400


class TestCORSSecurityConfiguration:
    """Tests for CORS security best practices."""

    def test_production_does_not_allow_all_origins(self) -> None:
        """Production should never allow all origins (*)."""
        with (
            patch("main._ensure_spacy_models"),
            patch.dict(
                "os.environ",
                {"ENVIRONMENT": "production", "CORS_ORIGINS": "https://app.example.com"},
            ),
        ):
            from main import create_app

            mock_settings = _make_mock_settings()
            with patch("main.Settings", return_value=mock_settings):
                app = create_app()

                # Find CORS middleware
                for middleware in app.user_middleware:
                    if middleware.cls == CORSMiddleware:
                        origins = middleware.kwargs.get("allow_origins", [])

                        # Should not be wildcard
                        assert origins != ["*"], "Production should not use wildcard origins"

                        # Should not be empty list meaning "all"
                        # (empty list in production means CORS disabled, which is OK)
                        break

    def test_development_default_origins_are_safe(self) -> None:
        """Development default origins should be localhost only."""
        with (
            patch("main._ensure_spacy_models"),
            patch.dict("os.environ", {"ENVIRONMENT": "development"}),
        ):
            # Remove CORS_ORIGINS to test defaults
            import os

            if "CORS_ORIGINS" in os.environ:
                del os.environ["CORS_ORIGINS"]

            from main import create_app

            mock_settings = _make_mock_settings()
            with patch("main.Settings", return_value=mock_settings):
                app = create_app()

                # Find CORS middleware
                for middleware in app.user_middleware:
                    if middleware.cls == CORSMiddleware:
                        origins = middleware.kwargs.get("allow_origins", [])

                        # All should be localhost
                        for origin in origins:
                            assert (
                                "localhost" in origin or "127.0.0.1" in origin
                            ), f"Development default {origin} should be localhost"
                        break

    def test_cors_methods_are_configured(self) -> None:
        """CORS should allow standard HTTP methods."""
        with (
            patch("main._ensure_spacy_models"),
            patch.dict("os.environ", {"ENVIRONMENT": "development"}),
        ):
            from main import create_app

            mock_settings = _make_mock_settings()
            with patch("main.Settings", return_value=mock_settings):
                app = create_app()

                # Find CORS middleware
                for middleware in app.user_middleware:
                    if middleware.cls == CORSMiddleware:
                        methods = middleware.kwargs.get("allow_methods", [])

                        # Should allow common methods
                        assert "GET" in methods
                        assert "POST" in methods
                        assert "PUT" in methods
                        assert "DELETE" in methods
                        assert "OPTIONS" in methods
                        break

    def test_cors_headers_are_configured(self) -> None:
        """CORS should allow standard headers including X-API-Key."""
        with (
            patch("main._ensure_spacy_models"),
            patch.dict("os.environ", {"ENVIRONMENT": "development"}),
        ):
            from main import create_app

            mock_settings = _make_mock_settings()
            with patch("main.Settings", return_value=mock_settings):
                app = create_app()

                # Find CORS middleware
                for middleware in app.user_middleware:
                    if middleware.cls == CORSMiddleware:
                        headers = middleware.kwargs.get("allow_headers", [])

                        # Should allow common headers
                        # "*" means all headers are allowed
                        assert (
                            headers == ["*"] or "X-API-Key" in headers or "x-api-key" in headers
                        ), "CORS should allow X-API-Key header"
                        break
