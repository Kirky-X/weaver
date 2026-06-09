# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for API Key management endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Import the router directly from the module
from api.endpoints.admin_keys import router


@pytest.fixture
def app() -> FastAPI:
    """Create FastAPI app with admin keys router."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """Mock database session."""
    return AsyncMock()


class TestApiKeyCreation:
    """Test API Key creation endpoint."""

    def test_create_api_key_success(self, client: TestClient) -> None:
        """Test successful API key creation."""
        with patch("api.endpoints.admin_keys.get_db") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value = mock_session

            # Mock database operations
            mock_session.execute.return_value = MagicMock()
            mock_session.commit.return_value = None

            response = client.post(
                "/api/v1/admin/api-keys",
                json={
                    "name": "Test Key",
                    "scopes": ["read", "write"],
                    "expires_in_days": 30,
                },
            )

            assert response.status_code == 201
            data = response.json()
            assert "key_id" in data
            assert "key" in data
            assert data["name"] == "Test Key"
            assert data["scopes"] == ["read", "write"]

    def test_create_api_key_with_default_scopes(self, client: TestClient) -> None:
        """Test API key creation with default scopes."""
        with patch("api.endpoints.admin_keys.get_db") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value = mock_session

            mock_session.execute.return_value = MagicMock()
            mock_session.commit.return_value = None

            response = client.post(
                "/api/v1/admin/api-keys",
                json={"name": "Default Scopes Key"},
            )

            assert response.status_code == 201
            data = response.json()
            assert data["scopes"] == ["read"]

    def test_create_api_key_with_expiration(self, client: TestClient) -> None:
        """Test API key creation with expiration."""
        with patch("api.endpoints.admin_keys.get_db") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value = mock_session

            mock_session.execute.return_value = MagicMock()
            mock_session.commit.return_value = None

            response = client.post(
                "/api/v1/admin/api-keys",
                json={
                    "name": "Expiring Key",
                    "expires_in_days": 7,
                },
            )

            assert response.status_code == 201
            data = response.json()
            assert "expires_at" in data

    def test_create_api_key_invalid_scopes(self, client: TestClient) -> None:
        """Test API key creation with invalid scopes."""
        response = client.post(
            "/api/v1/admin/api-keys",
            json={
                "name": "Invalid Scopes Key",
                "scopes": ["invalid_scope"],
            },
        )

        assert response.status_code == 422


class TestApiKeyValidation:
    """Test API Key validation."""

    def test_validate_api_key_success(self) -> None:
        """Test successful API key validation."""
        from api.endpoints.admin_keys import validate_api_key

        # Mock database session
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = {
            "key_id": str(uuid.uuid4()),
            "key_hash": "$2b$12$valid_hash",
            "scopes": ["read"],
            "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
            "is_active": True,
        }
        mock_session.execute.return_value = mock_result

        # Mock bcrypt check
        with patch("api.endpoints.admin_keys.bcrypt.checkpw") as mock_check:
            mock_check.return_value = True

            result = validate_api_key("test_key", mock_session)

            assert result is not None
            assert "key_id" in result

    def test_validate_api_key_expired(self) -> None:
        """Test validation of expired API key."""
        from api.endpoints.admin_keys import validate_api_key

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = {
            "key_id": str(uuid.uuid4()),
            "key_hash": "$2b$12$valid_hash",
            "scopes": ["read"],
            "expires_at": datetime.now(timezone.utc) - timedelta(days=1),
            "is_active": True,
        }
        mock_session.execute.return_value = mock_result

        with patch("api.endpoints.admin_keys.bcrypt.checkpw") as mock_check:
            mock_check.return_value = True

            result = validate_api_key("test_key", mock_session)

            assert result is None

    def test_validate_api_key_inactive(self) -> None:
        """Test validation of inactive API key."""
        from api.endpoints.admin_keys import validate_api_key

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = {
            "key_id": str(uuid.uuid4()),
            "key_hash": "$2b$12$valid_hash",
            "scopes": ["read"],
            "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
            "is_active": False,
        }
        mock_session.execute.return_value = mock_result

        with patch("api.endpoints.admin_keys.bcrypt.checkpw") as mock_check:
            mock_check.return_value = True

            result = validate_api_key("test_key", mock_session)

            assert result is None

    def test_validate_api_key_wrong_hash(self) -> None:
        """Test validation with wrong hash."""
        from api.endpoints.admin_keys import validate_api_key

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = {
            "key_id": str(uuid.uuid4()),
            "key_hash": "$2b$12$valid_hash",
            "scopes": ["read"],
            "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
            "is_active": True,
        }
        mock_session.execute.return_value = mock_result

        with patch("api.endpoints.admin_keys.bcrypt.checkpw") as mock_check:
            mock_check.return_value = False

            result = validate_api_key("wrong_key", mock_session)

            assert result is None

    def test_validate_api_key_not_found(self) -> None:
        """Test validation of non-existent API key."""
        from api.endpoints.admin_keys import validate_api_key

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = validate_api_key("non_existent_key", mock_session)

        assert result is None


class TestApiKeyRevocation:
    """Test API Key revocation endpoint."""

    def test_revoke_api_key_success(self, client: TestClient) -> None:
        """Test successful API key revocation."""
        with patch("api.endpoints.admin_keys.get_db") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value = mock_session

            # Mock key exists
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = {
                "key_id": str(uuid.uuid4()),
                "is_active": True,
            }
            mock_session.execute.return_value = mock_result
            mock_session.commit.return_value = None

            key_id = str(uuid.uuid4())
            response = client.delete(f"/api/v1/admin/api-keys/{key_id}")

            assert response.status_code == 200
            data = response.json()
            assert data["message"] == "API key revoked successfully"

    def test_revoke_api_key_not_found(self, client: TestClient) -> None:
        """Test revocation of non-existent API key."""
        with patch("api.endpoints.admin_keys.get_db") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value = mock_session

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_session.execute.return_value = mock_result

            key_id = str(uuid.uuid4())
            response = client.delete(f"/api/v1/admin/api-keys/{key_id}")

            assert response.status_code == 404

    def test_revoke_api_key_already_revoked(self, client: TestClient) -> None:
        """Test revocation of already revoked API key."""
        with patch("api.endpoints.admin_keys.get_db") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value = mock_session

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = {
                "key_id": str(uuid.uuid4()),
                "is_active": False,
            }
            mock_session.execute.return_value = mock_result

            key_id = str(uuid.uuid4())
            response = client.delete(f"/api/v1/admin/api-keys/{key_id}")

            assert response.status_code == 400


class TestMultipleApiKeys:
    """Test multiple API key support."""

    def test_multiple_keys_different_scopes(self, client: TestClient) -> None:
        """Test multiple keys with different scopes."""
        with patch("api.endpoints.admin_keys.get_db") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value = mock_session

            mock_session.execute.return_value = MagicMock()
            mock_session.commit.return_value = None

            # Create first key
            response1 = client.post(
                "/api/v1/admin/api-keys",
                json={
                    "name": "Read Key",
                    "scopes": ["read"],
                },
            )

            # Create second key
            response2 = client.post(
                "/api/v1/admin/api-keys",
                json={
                    "name": "Write Key",
                    "scopes": ["write"],
                },
            )

            assert response1.status_code == 201
            assert response2.status_code == 201

            data1 = response1.json()
            data2 = response2.json()

            assert data1["scopes"] == ["read"]
            assert data2["scopes"] == ["write"]
            assert data1["key_id"] != data2["key_id"]

    def test_list_api_keys(self, client: TestClient) -> None:
        """Test listing API keys."""
        with patch("api.endpoints.admin_keys.get_db") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value = mock_session

            mock_result = MagicMock()
            mock_result.fetchall.return_value = [
                {
                    "key_id": str(uuid.uuid4()),
                    "name": "Key 1",
                    "scopes": ["read"],
                    "created_at": datetime.now(timezone.utc),
                    "expires_at": None,
                    "is_active": True,
                },
                {
                    "key_id": str(uuid.uuid4()),
                    "name": "Key 2",
                    "scopes": ["write"],
                    "created_at": datetime.now(timezone.utc),
                    "expires_at": None,
                    "is_active": True,
                },
            ]
            mock_session.execute.return_value = mock_result

            response = client.get("/api/v1/admin/api-keys")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2


class TestEdgeCases:
    """Test edge cases."""

    def test_create_key_with_empty_name(self, client: TestClient) -> None:
        """Test creating key with empty name."""
        response = client.post(
            "/api/v1/admin/api-keys",
            json={"name": ""},
        )

        assert response.status_code == 422

    def test_create_key_with_long_name(self, client: TestClient) -> None:
        """Test creating key with very long name."""
        response = client.post(
            "/api/v1/admin/api-keys",
            json={"name": "a" * 256},
        )

        assert response.status_code == 422

    def test_revoke_key_with_invalid_uuid(self, client: TestClient) -> None:
        """Test revoking key with invalid UUID."""
        response = client.delete("/api/v1/admin/api-keys/invalid-uuid")

        assert response.status_code == 422
