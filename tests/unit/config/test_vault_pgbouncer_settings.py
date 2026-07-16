# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""PgBouncer configuration tests.

Verifies that PgBouncerSettings loads correctly
with proper defaults and does not affect existing behavior when disabled.
"""

from __future__ import annotations

from config.subconfigs import PgBouncerSettings, PostgresSettings


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
