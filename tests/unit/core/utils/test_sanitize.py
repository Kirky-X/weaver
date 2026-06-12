# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for sanitize utilities."""

from __future__ import annotations

import pytest

from core.utils.sanitize import sanitize_dsn


class TestSanitizeDSN:
    """Tests for sanitize_dsn function."""

    def test_sanitize_empty_string(self):
        """Test sanitizing empty string."""
        assert sanitize_dsn("") == ""
        assert sanitize_dsn(None) is None

    def test_sanitize_postgresql_dsn(self):
        """Test sanitizing PostgreSQL DSN."""
        dsn = "postgresql://user:secret123@localhost/db"
        result = sanitize_dsn(dsn)
        assert "secret123" not in result
        assert "user:***@localhost" in result

    def test_sanitize_postgresql_with_driver(self):
        """Test sanitizing PostgreSQL DSN with driver."""
        dsn = "postgresql+psycopg://admin:password@db.example.com:5432/mydb"
        result = sanitize_dsn(dsn)
        assert "password" not in result
        assert "admin:***@db.example.com" in result

    def test_sanitize_redis_url(self):
        """Test sanitizing Redis URL."""
        url = "redis://default:redispass@localhost:6379"
        result = sanitize_dsn(url)
        assert "redispass" not in result
        assert "default:***@localhost" in result

    def test_sanitize_neo4j_url(self):
        """Test sanitizing Neo4j bolt URL."""
        url = "bolt://neo4j:neopass@neo4j.local:7687"
        result = sanitize_dsn(url)
        assert "neopass" not in result
        assert "neo4j:***@neo4j.local" in result

    def test_sanitize_api_key_in_url(self):
        """Test sanitizing API key in URL parameters."""
        url = "https://api.example.com/data?api_key=sk-12345&other=value"
        result = sanitize_dsn(url)
        assert "sk-12345" not in result
        assert "api_key=***" in result

    def test_sanitize_password_param(self):
        """Test sanitizing password parameter."""
        url = "https://db.example.com/connect?password=secretpass&user=admin"
        result = sanitize_dsn(url)
        assert "secretpass" not in result
        assert "password=***" in result

    def test_sanitize_token_param(self):
        """Test sanitizing token parameter."""
        url = "https://service.example.com/api?token=abc123xyz"
        result = sanitize_dsn(url)
        assert "abc123xyz" not in result
        assert "token=***" in result

    def test_sanitize_secret_param(self):
        """Test sanitizing secret parameter."""
        url = "https://auth.example.com/validate?secret=mysecretvalue"
        result = sanitize_dsn(url)
        assert "mysecretvalue" not in result
        assert "secret=***" in result

    def test_sanitize_multiple_credentials(self):
        """Test sanitizing multiple credentials in one string."""
        url = "postgresql://user:pass@host/db?api_key=key123&password=dbpass"
        result = sanitize_dsn(url)
        assert "pass" not in result or "***" in result
        assert "key123" not in result
        assert "dbpass" not in result

    def test_sanitize_no_credentials(self):
        """Test that strings without credentials are unchanged."""
        url = "https://example.com/public/path"
        result = sanitize_dsn(url)
        assert result == url

    def test_sanitize_plain_text_without_sensitive_data(self):
        """Test plain text without sensitive data."""
        text = "This is just a normal log message without secrets"
        result = sanitize_dsn(text)
        assert result == text

    def test_sanitize_complex_connection_string(self):
        """Test sanitizing complex connection string."""
        conn_str = (
            "postgresql+async://app_user:P@ssw0rd!@prod-db.example.com:5432/appdb?sslmode=require"
        )
        result = sanitize_dsn(conn_str)
        # Password should be sanitized
        assert "P@ssw0rd!" not in result
        # Check that *** appears (password replaced)
        assert "***" in result

    def test_sanitize_case_insensitive(self):
        """Test case insensitive matching."""
        url = "https://api.example.com/data?API_KEY=secret123"
        result = sanitize_dsn(url)
        assert "secret123" not in result
        assert "API_KEY=***" in result
