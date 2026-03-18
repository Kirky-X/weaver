"""Unit tests for database initializer module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncpg

from core.db.initializer import (
    parse_dsn,
    ParsedDSN,
    check_database_exists,
    create_database,
    wait_for_postgres,
    verify_tables,
    run_migrations,
    initialize_database,
    REQUIRED_TABLES,
)


class TestParseDSN:
    """Tests for DSN parsing."""

    def test_parse_valid_dsn(self):
        """Test parsing a valid DSN."""
        dsn = "postgresql+asyncpg://user:password@localhost:5432/weaver"
        result = parse_dsn(dsn)

        assert result.driver == "postgresql+asyncpg"
        assert result.user == "user"
        assert result.password == "password"
        assert result.host == "localhost"
        assert result.port == 5432
        assert result.database == "weaver"

    def test_parse_dsn_with_ip(self):
        """Test parsing DSN with IP address."""
        dsn = "postgresql+asyncpg://postgres:secret@192.168.1.1:5432/mydb"
        result = parse_dsn(dsn)

        assert result.host == "192.168.1.1"
        assert result.database == "mydb"

    def test_parse_invalid_dsn(self):
        """Test parsing an invalid DSN raises error."""
        with pytest.raises(ValueError, match="Invalid DSN format"):
            parse_dsn("invalid-dsn")

    def test_parse_dsn_with_special_chars_in_password(self):
        """Test parsing DSN with special characters in password."""
        dsn = "postgresql+asyncpg://user:p@ss123@localhost:5432/db"
        result = parse_dsn(dsn)

        assert result.password == "p@ss123"


class TestCheckDatabaseExists:
    """Tests for database existence check."""

    @pytest.mark.asyncio
    async def test_database_exists(self):
        """Test when database exists."""
        parsed = ParsedDSN(
            driver="postgresql+asyncpg",
            user="user",
            password="pass",
            host="localhost",
            port=5432,
            database="weaver",
        )

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=1)
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)):
            result = await check_database_exists(parsed)

        assert result is True
        mock_conn.fetchval.assert_called_once()

    @pytest.mark.asyncio
    async def test_database_not_exists(self):
        """Test when database does not exist."""
        parsed = ParsedDSN(
            driver="postgresql+asyncpg",
            user="user",
            password="pass",
            host="localhost",
            port=5432,
            database="weaver",
        )

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=None)
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)):
            result = await check_database_exists(parsed)

        assert result is False


class TestCreateDatabase:
    """Tests for database creation."""

    @pytest.mark.asyncio
    async def test_create_database_success(self):
        """Test successful database creation."""
        parsed = ParsedDSN(
            driver="postgresql+asyncpg",
            user="user",
            password="pass",
            host="localhost",
            port=5432,
            database="newdb",
        )

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)):
            await create_database(parsed)

        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_database_already_exists(self):
        """Test creating database that already exists."""
        parsed = ParsedDSN(
            driver="postgresql+asyncpg",
            user="user",
            password="pass",
            host="localhost",
            port=5432,
            database="existingdb",
        )

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(
            side_effect=asyncpg.DuplicateDatabaseError()
        )
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)):
            await create_database(parsed)

    @pytest.mark.asyncio
    async def test_create_database_permission_denied(self):
        """Test database creation with insufficient privileges."""
        parsed = ParsedDSN(
            driver="postgresql+asyncpg",
            user="user",
            password="pass",
            host="localhost",
            port=5432,
            database="newdb",
        )

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(
            side_effect=asyncpg.InsufficientPrivilegeError()
        )
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)):
            with pytest.raises(RuntimeError, match="Permission denied"):
                await create_database(parsed)


class TestWaitForPostgres:
    """Tests for PostgreSQL availability check."""

    @pytest.mark.asyncio
    async def test_postgres_immediately_available(self):
        """Test when PostgreSQL is immediately available."""
        parsed = ParsedDSN(
            driver="postgresql+asyncpg",
            user="user",
            password="pass",
            host="localhost",
            port=5432,
            database="weaver",
        )

        mock_conn = AsyncMock()
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)):
            await wait_for_postgres(parsed, timeout=5.0)

    @pytest.mark.asyncio
    async def test_postgres_becomes_available(self):
        """Test when PostgreSQL becomes available after retries."""
        parsed = ParsedDSN(
            driver="postgresql+asyncpg",
            user="user",
            password="pass",
            host="localhost",
            port=5432,
            database="weaver",
        )

        mock_conn = AsyncMock()
        mock_conn.close = AsyncMock()

        call_count = 0

        async def mock_connect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OSError("Connection refused")
            return mock_conn

        with patch("asyncpg.connect", mock_connect):
            await wait_for_postgres(parsed, timeout=10.0)

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_postgres_timeout(self):
        """Test timeout when PostgreSQL is never available."""
        parsed = ParsedDSN(
            driver="postgresql+asyncpg",
            user="user",
            password="pass",
            host="localhost",
            port=5432,
            database="weaver",
        )

        with patch(
            "asyncpg.connect",
            AsyncMock(side_effect=OSError("Connection refused")),
        ):
            with patch("asyncio.sleep", AsyncMock()):
                with pytest.raises(RuntimeError, match="not available after"):
                    await wait_for_postgres(parsed, timeout=1.0)


class TestVerifyTables:
    """Tests for table verification."""

    @pytest.mark.asyncio
    async def test_all_tables_exist(self):
        """Test when all required tables exist."""
        dsn = "postgresql+asyncpg://user:pass@localhost:5432/weaver"

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            return_value=[{"tablename": table} for table in REQUIRED_TABLES]
        )
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)):
            result = await verify_tables(dsn)

        assert result is True

    @pytest.mark.asyncio
    async def test_missing_tables(self):
        """Test when some tables are missing."""
        dsn = "postgresql+asyncpg://user:pass@localhost:5432/weaver"

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            return_value=[
                {"tablename": "articles"},
                {"tablename": "article_vectors"},
            ]
        )
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)):
            result = await verify_tables(dsn)

        assert result is False

    @pytest.mark.asyncio
    async def test_no_tables(self):
        """Test when no tables exist."""
        dsn = "postgresql+asyncpg://user:pass@localhost:5432/weaver"

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)):
            result = await verify_tables(dsn)

        assert result is False


class TestRunMigrations:
    """Tests for migration execution."""

    def test_run_migrations_success(self):
        """Test successful migration execution."""
        with patch("alembic.command.upgrade") as mock_upgrade:
            run_migrations(
                "alembic.ini",
                "src/alembic",
                "postgresql+asyncpg://user:pass@localhost:5432/weaver",
            )

            mock_upgrade.assert_called_once()
            call_args = mock_upgrade.call_args
            assert call_args[0][1] == "head"

    def test_run_migrations_failure(self):
        """Test migration failure."""
        with (
            patch(
                "alembic.command.upgrade",
                side_effect=Exception("Migration failed"),
            ),
            pytest.raises(Exception, match="Migration failed"),
        ):
            run_migrations(
                "alembic.ini",
                "src/alembic",
                "postgresql+asyncpg://user:pass@localhost:5432/weaver",
            )


class TestInitializeDatabase:
    """Tests for main initialization function."""

    @pytest.mark.asyncio
    async def test_initialize_existing_database_with_tables(self):
        """Test initialization when database and tables exist."""
        dsn = "postgresql+asyncpg://user:pass@localhost:5432/weaver"

        with (
            patch(
                "core.db.initializer.wait_for_postgres",
                AsyncMock(),
            ) as mock_wait,
            patch(
                "core.db.initializer.check_database_exists",
                AsyncMock(return_value=True),
            ) as mock_check,
            patch(
                "core.db.initializer.verify_tables",
                AsyncMock(return_value=True),
            ) as mock_verify,
        ):
            result = await initialize_database(dsn)

        assert result["database_created"] is False
        assert result["migrations_run"] is False
        assert result["tables_verified"] is True

    @pytest.mark.asyncio
    async def test_initialize_new_database(self):
        """Test initialization when database does not exist."""
        dsn = "postgresql+asyncpg://user:pass@localhost:5432/weaver"

        with (
            patch(
                "core.db.initializer.wait_for_postgres",
                AsyncMock(),
            ),
            patch(
                "core.db.initializer.check_database_exists",
                AsyncMock(return_value=False),
            ),
            patch(
                "core.db.initializer.create_database",
                AsyncMock(),
            ),
            patch(
                "core.db.initializer.verify_tables",
                AsyncMock(side_effect=[False, True]),
            ),
            patch(
                "core.db.initializer.run_migrations",
            ),
        ):
            result = await initialize_database(dsn)

        assert result["database_created"] is True
        assert result["migrations_run"] is True
        assert result["tables_verified"] is True

    @pytest.mark.asyncio
    async def test_initialize_migration_failure(self):
        """Test initialization when migration fails to create tables."""
        dsn = "postgresql+asyncpg://user:pass@localhost:5432/weaver"

        with (
            patch(
                "core.db.initializer.wait_for_postgres",
                AsyncMock(),
            ),
            patch(
                "core.db.initializer.check_database_exists",
                AsyncMock(return_value=True),
            ),
            patch(
                "core.db.initializer.verify_tables",
                AsyncMock(return_value=False),
            ),
            patch(
                "core.db.initializer.run_migrations",
            ),
        ):
            with pytest.raises(RuntimeError, match="Tables still missing"):
                await initialize_database(dsn)
