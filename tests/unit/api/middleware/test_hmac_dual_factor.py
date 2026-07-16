# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for HMAC dual-factor authentication.

TDD Phase 1: Write tests first, then implement.
"""

from __future__ import annotations

import hashlib
import hmac
import sys
import time
from unittest.mock import AsyncMock, MagicMock

# Mock setfit before any imports that trigger the chain
if "setfit" not in sys.modules:
    sys.modules["setfit"] = MagicMock()
    sys.modules["setfit.span"] = MagicMock()
    sys.modules["setfit.span.trainer"] = MagicMock()

import pytest

from api.middleware.hmac_auth import HMACSignatureMiddleware


class TestHMACDualFactor:
    """Test HMAC + API Key dual-factor verification."""

    def _make_signature(
        self, secret_key: str, timestamp: str, method: str, path: str, body: str = ""
    ) -> str:
        """Helper to create a valid HMAC signature."""
        message = f"{timestamp}:{method}:{path}:{body}"
        return hmac.new(
            secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @pytest.mark.asyncio
    async def test_hmac_with_api_key_dual_factor(self) -> None:
        """HMAC + API Key dual-factor should require both."""
        secret_key = "test-secret"
        api_key = "test-api-key"
        middleware = HMACSignatureMiddleware(
            app=MagicMock(),
            secret_key=secret_key,
            api_key=api_key,
        )

        timestamp = str(time.time())
        signature = self._make_signature(secret_key, timestamp, "GET", "/api/v1/test")

        mock_request = MagicMock()
        mock_request.url.path = "/api/v1/test"
        mock_request.method = "GET"
        mock_request.headers = {
            "X-Signature": signature,
            "X-Timestamp": timestamp,
            "X-API-Key": "test-api-key",
        }
        mock_request.body = AsyncMock(return_value=b"")

        mock_call_next = AsyncMock(return_value=MagicMock())
        response = await middleware.dispatch(mock_request, mock_call_next)

        # Should pass - both HMAC and API key are valid
        mock_call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_401(self) -> None:
        """Missing API key when dual-factor enabled should return 401."""
        secret_key = "test-secret"
        api_key = "test-api-key"
        middleware = HMACSignatureMiddleware(
            app=MagicMock(),
            secret_key=secret_key,
            api_key=api_key,
        )

        timestamp = str(time.time())
        signature = self._make_signature(secret_key, timestamp, "GET", "/api/v1/test")

        mock_request = MagicMock()
        mock_request.url.path = "/api/v1/test"
        mock_request.method = "GET"
        mock_request.headers = {
            "X-Signature": signature,
            "X-Timestamp": timestamp,
            # No X-API-Key header
        }
        mock_request.body = AsyncMock(return_value=b"")

        mock_call_next = AsyncMock()
        response = await middleware.dispatch(mock_request, mock_call_next)

        # Should return 401
        assert response.status_code == 401
        mock_call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_api_key_returns_401(self) -> None:
        """Invalid API key when dual-factor enabled should return 401."""
        secret_key = "test-secret"
        api_key = "test-api-key"
        middleware = HMACSignatureMiddleware(
            app=MagicMock(),
            secret_key=secret_key,
            api_key=api_key,
        )

        timestamp = str(time.time())
        signature = self._make_signature(secret_key, timestamp, "GET", "/api/v1/test")

        mock_request = MagicMock()
        mock_request.url.path = "/api/v1/test"
        mock_request.method = "GET"
        mock_request.headers = {
            "X-Signature": signature,
            "X-Timestamp": timestamp,
            "X-API-Key": "wrong-key",
        }
        mock_request.body = AsyncMock(return_value=b"")

        mock_call_next = AsyncMock()
        response = await middleware.dispatch(mock_request, mock_call_next)

        # Should return 401
        assert response.status_code == 401
        mock_call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_hmac_only_no_api_key_required(self) -> None:
        """Without api_key configured, API key should not be required."""
        secret_key = "test-secret"
        middleware = HMACSignatureMiddleware(
            app=MagicMock(),
            secret_key=secret_key,
            api_key=None,
        )

        timestamp = str(time.time())
        signature = self._make_signature(secret_key, timestamp, "GET", "/api/v1/test")

        mock_request = MagicMock()
        mock_request.url.path = "/api/v1/test"
        mock_request.method = "GET"
        mock_request.headers = {
            "X-Signature": signature,
            "X-Timestamp": timestamp,
        }
        mock_request.body = AsyncMock(return_value=b"")

        mock_call_next = AsyncMock(return_value=MagicMock())
        response = await middleware.dispatch(mock_request, mock_call_next)

        # Should pass - no API key required
        mock_call_next.assert_called_once()


class TestHMACValidateConfig:
    """Test HMAC configuration validation."""

    def test_validate_config_no_warnings(self) -> None:
        """No warnings when both secret_key and api_key are configured."""
        warnings = HMACSignatureMiddleware.validate_config("secret", "api-key")
        assert len(warnings) == 0

    def test_validate_config_warns_on_missing_api_key(self) -> None:
        """Warning when HMAC enabled without API key."""
        warnings = HMACSignatureMiddleware.validate_config("secret", None)
        assert len(warnings) == 1
        assert "dual-factor" in warnings[0].lower() or "api key" in warnings[0].lower()

    def test_validate_config_warns_on_missing_secret(self) -> None:
        """Warning when secret_key is not configured."""
        warnings = HMACSignatureMiddleware.validate_config(None, "api-key")
        assert len(warnings) >= 1
        assert any("secret" in w.lower() for w in warnings)
