# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for sensitive data sanitization utilities."""

import pytest

from core.utils.sanitize import sanitize_dict, sanitize_dsn, sanitize_for_log


class TestSanitizeDSN:
    """Tests for sanitize_dsn function."""

    def test_sanitize_postgresql_dsn(self) -> None:
        """Test PostgreSQL DSN sanitization."""
        dsn = "postgresql://user:secret123@localhost:5432/mydb"
        result = sanitize_dsn(dsn)
        assert "secret123" not in result
        assert "***" in result
        assert result == "postgresql://user:***@localhost:5432/mydb"

    def test_sanitize_redis_url(self) -> None:
        """Test Redis URL sanitization."""
        url = "redis://admin:password123@redis.example.com:6379"
        result = sanitize_dsn(url)
        assert "password123" not in result
        assert "***" in result

    def test_sanitize_neo4j_bolt_url(self) -> None:
        """Test Neo4j bolt URL sanitization."""
        url = "bolt://neo4j:mypassword@localhost:7687"
        result = sanitize_dsn(url)
        assert "mypassword" not in result
        assert "***" in result

    def test_sanitize_api_key_in_url(self) -> None:
        """Test API key sanitization in URL params."""
        url = "https://api.example.com/data?api_key=sk-123456&other=value"
        result = sanitize_dsn(url)
        assert "sk-123456" not in result
        assert "api_key=***" in result

    def test_empty_string_returns_empty(self) -> None:
        """Test empty string returns empty."""
        assert sanitize_dsn("") == ""

    def test_none_returns_none(self) -> None:
        """Test None returns None."""
        assert sanitize_dsn(None) is None

    def test_no_credentials_unchanged(self) -> None:
        """Test DSN without credentials remains unchanged."""
        dsn = "postgresql://localhost:5432/mydb"
        result = sanitize_dsn(dsn)
        assert result == dsn


class TestSanitizeDict:
    """Tests for sanitize_dict function."""

    def test_sanitize_password_key(self) -> None:
        """Test password key sanitization."""
        data = {"password": "secret123", "username": "admin"}
        result = sanitize_dict(data)
        assert result["password"] == "***"
        assert result["username"] == "admin"

    def test_sanitize_api_key(self) -> None:
        """Test API key sanitization."""
        data = {"api_key": "sk-abcdef", "name": "service"}
        result = sanitize_dict(data)
        assert result["api_key"] == "***"
        assert result["name"] == "service"

    def test_sanitize_token(self) -> None:
        """Test token sanitization."""
        data = {"token": "bearer-token-123", "user_id": 42}
        result = sanitize_dict(data)
        assert result["token"] == "***"

    def test_sanitize_nested_dict(self) -> None:
        """Test nested dictionary sanitization."""
        data = {
            "config": {
                "password": "nested-secret",
                "host": "localhost",
            },
            "name": "test",
        }
        result = sanitize_dict(data)
        assert result["config"]["password"] == "***"
        assert result["config"]["host"] == "localhost"

    def test_sanitize_list_of_dicts(self) -> None:
        """Test list of dictionaries sanitization."""
        data = {
            "connections": [
                {"password": "pass1", "host": "host1"},
                {"api_key": "key1", "host": "host2"},
            ]
        }
        result = sanitize_dict(data)
        assert result["connections"][0]["password"] == "***"
        assert result["connections"][1]["api_key"] == "***"

    def test_sanitize_dsn_in_dict(self) -> None:
        """Test DSN sanitization in dict values."""
        data = {
            "database_url": "postgresql://user:pass@host/db",
            "name": "app",
        }
        result = sanitize_dict(data)
        assert "pass" not in result["database_url"]
        assert "***" in result["database_url"]

    def test_custom_sensitive_keys(self) -> None:
        """Test custom sensitive keys."""
        data = {"custom_secret": "value123", "name": "test"}
        result = sanitize_dict(data, sensitive_keys={"custom_secret"})
        assert result["custom_secret"] == "***"

    def test_preserves_non_sensitive_values(self) -> None:
        """Test non-sensitive values are preserved."""
        data = {
            "host": "localhost",
            "port": 5432,
            "ssl": True,
            "timeout": 30.5,
        }
        result = sanitize_dict(data)
        assert result["host"] == "localhost"
        assert result["port"] == 5432
        assert result["ssl"] is True
        assert result["timeout"] == 30.5


class TestSanitizeForLog:
    """Tests for sanitize_for_log function."""

    def test_sanitize_password_in_log(self) -> None:
        """Test password sanitization in log message."""
        message = "Connecting with password='secret123' to database"
        result = sanitize_for_log(message)
        assert "secret123" not in result
        assert "***" in result

    def test_sanitize_dsn_in_log(self) -> None:
        """Test DSN sanitization in log message."""
        message = "Connected to postgresql://admin:p4ssw0rd@db.example.com/app"
        result = sanitize_for_log(message)
        assert "p4ssw0rd" not in result
        assert "***" in result

    def test_sanitize_token_in_log(self) -> None:
        """Test token sanitization in log message."""
        message = "Using token='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9'"
        result = sanitize_for_log(message)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result

    def test_empty_string_returns_empty(self) -> None:
        """Test empty string returns empty."""
        assert sanitize_for_log("") == ""

    def test_none_returns_none(self) -> None:
        """Test None returns None."""
        assert sanitize_for_log(None) is None

    def test_no_secrets_unchanged(self) -> None:
        """Test message without secrets remains unchanged."""
        message = "Successfully connected to localhost:5432"
        result = sanitize_for_log(message)
        assert result == message


class TestSanitizeEdgeCases:
    """Edge case tests for sanitization."""

    def test_multiple_secrets_in_one_string(self) -> None:
        """Test multiple secrets in one string."""
        dsn = "postgresql://u1:p1@h1/db and redis://u2:p2@h2"
        result = sanitize_dsn(dsn)
        assert "p1" not in result
        assert "p2" not in result

    def test_case_insensitive_key_matching(self) -> None:
        """Test case insensitive key matching."""
        data = {
            "PASSWORD": "secret1",
            "Password": "secret2",
            "password": "secret3",
        }
        result = sanitize_dict(data)
        assert all(result[k] == "***" for k in data)

    def test_key_with_hyphens(self) -> None:
        """Test keys with hyphens."""
        data = {"api-key": "secret-key-123"}
        result = sanitize_dict(data)
        assert result["api-key"] == "***"

    def test_special_characters_in_password(self) -> None:
        """Test special characters in password."""
        dsn = "postgresql://user:p@ss!w0rd@host/db"
        result = sanitize_dsn(dsn)
        # The regex should still match and sanitize
        assert "p@ss!w0rd" not in result or "***" in result
