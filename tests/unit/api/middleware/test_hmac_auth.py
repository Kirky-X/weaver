# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for HMAC signature middleware."""

import hashlib
import hmac
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middleware.hmac_auth import HMACSignatureMiddleware


class TestHMACSignatureMiddleware:
    """Tests for HMAC signature verification middleware."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.secret_key = "test-secret-key-for-hmac-signature"
        self.app = FastAPI()
        self.app.add_middleware(HMACSignatureMiddleware, secret_key=self.secret_key)

        @self.app.get("/test")
        async def test_endpoint() -> dict:
            return {"message": "success"}

        @self.app.post("/test")
        async def test_post_endpoint() -> dict:
            return {"received": "ok"}

        @self.app.get("/health")
        async def health_endpoint() -> dict:
            return {"status": "healthy"}

        @self.app.get("/metrics")
        async def metrics_endpoint() -> dict:
            return {"metrics": "data"}

        self.client = TestClient(self.app)

    def _calculate_signature(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """Calculate HMAC signature for testing."""
        message = f"{timestamp}:{method}:{path}:{body}"
        return hmac.new(
            self.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def test_valid_signature_passes(self) -> None:
        """Test that request with valid signature passes."""
        timestamp = str(time.time())
        signature = self._calculate_signature(timestamp, "GET", "/test")

        response = self.client.get(
            "/test",
            headers={"X-Signature": signature, "X-Timestamp": timestamp},
        )

        assert response.status_code == 200
        assert response.json() == {"message": "success"}

    def test_missing_signature_headers_returns_401(self) -> None:
        """Test that missing signature headers return 401."""
        response = self.client.get("/test")

        assert response.status_code == 401
        assert response.json()["detail"] == "missing_signature_headers"

    def test_missing_signature_header_returns_401(self) -> None:
        """Test that missing X-Signature header returns 401."""
        timestamp = str(time.time())

        response = self.client.get(
            "/test",
            headers={"X-Timestamp": timestamp},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "missing_signature_headers"

    def test_missing_timestamp_header_returns_401(self) -> None:
        """Test that missing X-Timestamp header returns 401."""
        signature = "some-signature"

        response = self.client.get(
            "/test",
            headers={"X-Signature": signature},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "missing_signature_headers"

    def test_expired_timestamp_returns_401(self) -> None:
        """Test that expired timestamp returns 401."""
        # Use timestamp from 60 seconds ago (outside ±30 second window)
        timestamp = str(time.time() - 60)
        signature = self._calculate_signature(timestamp, "GET", "/test")

        response = self.client.get(
            "/test",
            headers={"X-Signature": signature, "X-Timestamp": timestamp},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "signature_expired"

    def test_future_timestamp_returns_401(self) -> None:
        """Test that future timestamp returns 401."""
        # Use timestamp from 60 seconds in the future (outside ±30 second window)
        timestamp = str(time.time() + 60)
        signature = self._calculate_signature(timestamp, "GET", "/test")

        response = self.client.get(
            "/test",
            headers={"X-Signature": signature, "X-Timestamp": timestamp},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "signature_expired"

    def test_invalid_signature_returns_401(self) -> None:
        """Test that invalid signature returns 401."""
        timestamp = str(time.time())
        invalid_signature = "invalid-signature"

        response = self.client.get(
            "/test",
            headers={"X-Signature": invalid_signature, "X-Timestamp": timestamp},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "missing_signature_headers"

    def test_invalid_timestamp_format_returns_401(self) -> None:
        """Test that invalid timestamp format returns 401."""
        signature = "some-signature"

        response = self.client.get(
            "/test",
            headers={"X-Signature": signature, "X-Timestamp": "invalid-timestamp"},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "missing_signature_headers"

    def test_health_endpoint_skips_signature(self) -> None:
        """Test that /health endpoint skips signature verification."""
        response = self.client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_metrics_endpoint_skips_signature(self) -> None:
        """Test that /metrics endpoint skips signature verification."""
        response = self.client.get("/metrics")

        assert response.status_code == 200
        assert response.json() == {"metrics": "data"}

    def test_post_request_signature(self) -> None:
        """Test signature verification for POST request with body."""
        timestamp = str(time.time())
        body = '{"key": "value"}'
        signature = self._calculate_signature(timestamp, "POST", "/test", body)

        response = self.client.post(
            "/test",
            content=body,
            headers={
                "X-Signature": signature,
                "X-Timestamp": timestamp,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 200

    def test_post_request_wrong_body_signature(self) -> None:
        """Test that POST request with wrong body signature fails."""
        timestamp = str(time.time())
        body = '{"key": "value"}'
        wrong_body = '{"key": "wrong"}'
        signature = self._calculate_signature(timestamp, "POST", "/test", wrong_body)

        response = self.client.post(
            "/test",
            content=body,
            headers={
                "X-Signature": signature,
                "X-Timestamp": timestamp,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "missing_signature_headers"

    def test_signature_within_tolerance_window(self) -> None:
        """Test that signature within ±30 second window passes."""
        # Use timestamp from 25 seconds ago (within tolerance)
        timestamp = str(time.time() - 25)
        signature = self._calculate_signature(timestamp, "GET", "/test")

        response = self.client.get(
            "/test",
            headers={"X-Signature": signature, "X-Timestamp": timestamp},
        )

        assert response.status_code == 200

    def test_signature_at_tolerance_boundary(self) -> None:
        """Test signature near tolerance boundary."""
        # Use timestamp from 29 seconds ago (just inside boundary)
        timestamp = str(time.time() - 29)
        signature = self._calculate_signature(timestamp, "GET", "/test")

        response = self.client.get(
            "/test",
            headers={"X-Signature": signature, "X-Timestamp": timestamp},
        )

        # Should pass (within tolerance)
        assert response.status_code == 200

    def test_different_paths_produce_different_signatures(self) -> None:
        """Test that different paths produce different signatures."""
        timestamp = str(time.time())
        signature_test = self._calculate_signature(timestamp, "GET", "/test")
        signature_other = self._calculate_signature(timestamp, "GET", "/other")

        # Signatures should be different
        assert signature_test != signature_other

        # Using /test signature for /other path should fail HMAC verification
        # Add a route for /other so the middleware processes it
        @self.app.get("/other")
        async def other_endpoint() -> dict:
            return {"other": True}

        response = self.client.get(
            "/other",
            headers={"X-Signature": signature_test, "X-Timestamp": timestamp},
        )

        # HMAC verification fails because path doesn't match
        assert response.status_code == 401

    def test_different_methods_produce_different_signatures(self) -> None:
        """Test that different HTTP methods produce different signatures."""
        timestamp = str(time.time())
        signature_get = self._calculate_signature(timestamp, "GET", "/test")
        signature_post = self._calculate_signature(timestamp, "POST", "/test")

        # GET signature should not work for POST
        response = self.client.post(
            "/test",
            content="{}",
            headers={
                "X-Signature": signature_get,
                "X-Timestamp": timestamp,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "missing_signature_headers"


class TestHMACSignatureMiddlewareConfiguration:
    """Tests for middleware configuration."""

    def test_middleware_with_empty_secret_key(self) -> None:
        """Test middleware behavior with empty secret key."""
        app = FastAPI()
        app.add_middleware(HMACSignatureMiddleware, secret_key="")

        @app.get("/test")
        async def test_endpoint() -> dict:
            return {"message": "success"}

        client = TestClient(app)
        timestamp = str(time.time())

        # Calculate signature with empty key
        message = f"{timestamp}:GET:/test:"
        signature = hmac.new(
            b"",
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        response = client.get(
            "/test",
            headers={"X-Signature": signature, "X-Timestamp": timestamp},
        )

        # Should still work with empty key
        assert response.status_code == 200

    def test_middleware_with_special_characters_in_secret(self) -> None:
        """Test middleware with special characters in secret key."""
        secret_key = "test-secret-with-special-chars!@#$%^&*()"
        app = FastAPI()
        app.add_middleware(HMACSignatureMiddleware, secret_key=secret_key)

        @app.get("/test")
        async def test_endpoint() -> dict:
            return {"message": "success"}

        client = TestClient(app)
        timestamp = str(time.time())

        # Calculate signature with special character key
        message = f"{timestamp}:GET:/test:"
        signature = hmac.new(
            secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        response = client.get(
            "/test",
            headers={"X-Signature": signature, "X-Timestamp": timestamp},
        )

        assert response.status_code == 200
