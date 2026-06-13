# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Vault and PgBouncer configuration tests.

Verifies that VaultSettings and PgBouncerSettings load correctly
with proper defaults and do not affect existing behavior when disabled.
"""

from __future__ import annotations

from config.subconfigs import PgBouncerSettings, PostgresSettings, VaultSettings


class TestVaultSettings:
    """Verify VaultSettings configuration model."""

    def test_default_disabled(self) -> None:
        """Vault should be disabled by default."""
        settings = VaultSettings()
        assert settings.enabled is False

    def test_default_url(self) -> None:
        """Default Vault URL should be localhost:8200."""
        settings = VaultSettings()
        assert settings.url == "http://localhost:8200"

    def test_default_token_empty(self) -> None:
        """Default Vault token should be empty."""
        settings = VaultSettings()
        assert settings.token == ""

    def test_default_mount_path(self) -> None:
        """Default mount path should be secret/weaver."""
        settings = VaultSettings()
        assert settings.mount_path == "secret/weaver"

    def test_default_secret_keys(self) -> None:
        """Default secret keys should include core passwords and API keys."""
        settings = VaultSettings()
        assert "postgres/password" in settings.secret_keys
        assert "neo4j/password" in settings.secret_keys
        assert "redis/password" in settings.secret_keys
        assert "api/api_key" in settings.secret_keys
        assert "api/admin_api_key" in settings.secret_keys

    def test_custom_enabled(self) -> None:
        """Vault can be enabled with custom settings."""
        settings = VaultSettings(
            enabled=True,
            url="https://vault.example.com:8200",
            token="hvs.xxx",
        )
        assert settings.enabled is True
        assert settings.url == "https://vault.example.com:8200"
        assert settings.token == "hvs.xxx"


class TestPgBouncerSettings:
    """Verify PgBouncerSettings configuration model."""

    def test_default_disabled(self) -> None:
        """PgBouncer should be disabled by default."""
        settings = PgBouncerSettings()
        assert settings.enabled is False

    def test_default_host_port(self) -> None:
        """Default PgBouncer host:port should be localhost:6432."""
        settings = PgBouncerSettings()
        assert settings.host == "localhost"
        assert settings.port == 6432

    def test_default_pool_mode(self) -> None:
        """Default pool mode should be transaction."""
        settings = PgBouncerSettings()
        assert settings.pool_mode == "transaction"

    def test_default_max_client_conn(self) -> None:
        """Default max client connections should be 100."""
        settings = PgBouncerSettings()
        assert settings.max_client_conn == 100

    def test_custom_enabled(self) -> None:
        """PgBouncer can be enabled with custom settings."""
        settings = PgBouncerSettings(
            enabled=True,
            host="pgbouncer.internal",
            port=6432,
            pool_mode="session",
        )
        assert settings.enabled is True
        assert settings.host == "pgbouncer.internal"
        assert settings.pool_mode == "session"


class TestPostgresSettingsPgBouncer:
    """Verify PostgresSettings.pgbouncer_dsn() method."""

    def test_pgbouncer_dsn(self) -> None:
        """PgBouncer DSN should point to PgBouncer proxy."""
        settings = PostgresSettings(
            user="weaver",
            password="secret",
            database="weaver_db",
        )
        dsn = settings.pgbouncer_dsn("pgbouncer.internal", 6432)
        assert dsn == "postgresql+asyncpg://weaver:secret@pgbouncer.internal:6432/weaver_db"

    def test_direct_dsn_unchanged(self) -> None:
        """Direct DSN should not be affected by PgBouncer settings."""
        settings = PostgresSettings(
            host="db.internal",
            port=5432,
            user="weaver",
            password="secret",
            database="weaver_db",
        )
        assert settings.dsn == "postgresql+asyncpg://weaver:secret@db.internal:5432/weaver_db"
