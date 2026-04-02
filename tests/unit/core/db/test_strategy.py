# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for database strategy factory."""

import pytest

from core.db.strategy import DatabaseStrategy


class TestDatabaseStrategy:
    """Tests for DatabaseStrategy dataclass."""

    def test_dataclass_is_frozen(self) -> None:
        """DatabaseStrategy should be immutable."""
        strategy = DatabaseStrategy(
            relational_pool=None,  # type: ignore[arg-type]
            graph_pool=None,  # type: ignore[arg-type]
            relational_type="postgresql",
            graph_type="none",
        )
        with pytest.raises(AttributeError):
            strategy.relational_type = "duckdb"  # type: ignore[misc]

    def test_dataclass_fields(self) -> None:
        """DatabaseStrategy should have expected fields."""
        strategy = DatabaseStrategy(
            relational_pool=None,  # type: ignore[arg-type]
            graph_pool=None,  # type: ignore[arg-type]
            relational_type="duckdb",
            graph_type="ladybug",
        )
        assert strategy.relational_type == "duckdb"
        assert strategy.graph_type == "ladybug"
        assert strategy.graph_pool is None

    def test_relational_type_validation(self) -> None:
        """relational_type should accept valid values."""
        for rel_type in ["postgresql", "duckdb"]:
            strategy = DatabaseStrategy(
                relational_pool=None,  # type: ignore[arg-type]
                graph_pool=None,  # type: ignore[arg-type]
                relational_type=rel_type,
                graph_type="none",
            )
            assert strategy.relational_type == rel_type

    def test_graph_type_validation(self) -> None:
        """graph_type should accept valid values."""
        for graph_type in ["neo4j", "ladybug", "none"]:
            strategy = DatabaseStrategy(
                relational_pool=None,  # type: ignore[arg-type]
                graph_pool=None,  # type: ignore[arg-type]
                relational_type="postgresql",
                graph_type=graph_type,
            )
            assert strategy.graph_type == graph_type


class TestCreateStrategy:
    """Tests for create_strategy factory function."""

    @pytest.mark.asyncio
    async def test_creates_postgresql_strategy_when_available(self, monkeypatch) -> None:
        """Should create PostgreSQL strategy when database is available."""
        from unittest.mock import AsyncMock, MagicMock

        from config.settings import Neo4jSettings, PostgresSettings

        # Mock PostgresPool at its source module
        mock_pg_pool = MagicMock()
        mock_pg_pool.startup = AsyncMock()
        monkeypatch.setattr("core.db.postgres.PostgresPool", lambda **kwargs: mock_pg_pool)

        from core.db.strategy import create_strategy

        pg_settings = PostgresSettings(host="localhost", password="test")
        neo4j_settings = Neo4jSettings(enabled=False)

        strategy = await create_strategy(
            pg_settings=pg_settings,
            neo4j_settings=neo4j_settings,
        )

        assert strategy.relational_type == "postgresql"
        assert strategy.graph_type == "none"
        mock_pg_pool.startup.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_to_duckdb_when_postgres_unavailable(self, monkeypatch) -> None:
        """Should fallback to DuckDB when PostgreSQL is unavailable."""
        from unittest.mock import AsyncMock, MagicMock

        from config.settings import DuckDBSettings, Neo4jSettings, PostgresSettings

        # Mock PostgresPool to fail
        def mock_pg_fail(**kwargs):
            pool = MagicMock()
            pool.startup = AsyncMock(side_effect=ConnectionError("PostgreSQL unavailable"))
            return pool

        monkeypatch.setattr("core.db.postgres.PostgresPool", mock_pg_fail)

        # Mock DuckDBPool
        mock_duckdb_pool = MagicMock()
        mock_duckdb_pool.startup = AsyncMock()
        monkeypatch.setattr("core.db.duckdb_pool.DuckDBPool", lambda **kwargs: mock_duckdb_pool)

        from core.db.strategy import create_strategy

        pg_settings = PostgresSettings(host="localhost", password="test")
        neo4j_settings = Neo4jSettings(enabled=False)
        duckdb_settings = DuckDBSettings(enabled=True)

        strategy = await create_strategy(
            pg_settings=pg_settings,
            neo4j_settings=neo4j_settings,
            duckdb_settings=duckdb_settings,
        )

        assert strategy.relational_type == "duckdb"
        mock_duckdb_pool.startup.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_when_both_postgres_and_duckdb_unavailable(self, monkeypatch) -> None:
        """Should raise when PostgreSQL unavailable and DuckDB disabled."""
        from unittest.mock import AsyncMock, MagicMock

        from config.settings import DuckDBSettings, Neo4jSettings, PostgresSettings

        # Mock PostgresPool to fail
        def mock_pg_fail(**kwargs):
            pool = MagicMock()
            pool.startup = AsyncMock(side_effect=ConnectionError("PostgreSQL unavailable"))
            return pool

        monkeypatch.setattr("core.db.postgres.PostgresPool", mock_pg_fail)

        from core.db.strategy import create_strategy

        pg_settings = PostgresSettings(host="localhost", password="test")
        neo4j_settings = Neo4jSettings(enabled=False)
        duckdb_settings = DuckDBSettings(enabled=False)

        with pytest.raises(
            RuntimeError, match="PostgreSQL unavailable and DuckDB fallback disabled"
        ):
            await create_strategy(
                pg_settings=pg_settings,
                neo4j_settings=neo4j_settings,
                duckdb_settings=duckdb_settings,
            )

    @pytest.mark.asyncio
    async def test_creates_neo4j_strategy_when_enabled_and_available(self, monkeypatch) -> None:
        """Should create Neo4j strategy when enabled and available."""
        from unittest.mock import AsyncMock, MagicMock

        from config.settings import Neo4jSettings, PostgresSettings

        # Mock pools
        mock_pg_pool = MagicMock()
        mock_pg_pool.startup = AsyncMock()

        mock_neo4j_pool = MagicMock()
        mock_neo4j_pool.startup = AsyncMock()

        monkeypatch.setattr("core.db.postgres.PostgresPool", lambda **kwargs: mock_pg_pool)
        monkeypatch.setattr("core.db.neo4j.Neo4jPool", lambda **kwargs: mock_neo4j_pool)

        from core.db.strategy import create_strategy

        pg_settings = PostgresSettings(host="localhost", password="test")
        neo4j_settings = Neo4jSettings(enabled=True, uri="bolt://localhost:7687", password="test")

        strategy = await create_strategy(
            pg_settings=pg_settings,
            neo4j_settings=neo4j_settings,
        )

        assert strategy.relational_type == "postgresql"
        assert strategy.graph_type == "neo4j"
        mock_neo4j_pool.startup.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_to_ladybug_when_neo4j_unavailable(self, monkeypatch) -> None:
        """Should fallback to LadybugDB when Neo4j is unavailable."""
        from unittest.mock import AsyncMock, MagicMock

        from config.settings import LadybugSettings, Neo4jSettings, PostgresSettings

        # Mock pools
        mock_pg_pool = MagicMock()
        mock_pg_pool.startup = AsyncMock()

        def mock_neo4j_fail(**kwargs):
            pool = MagicMock()
            pool.startup = AsyncMock(side_effect=ConnectionError("Neo4j unavailable"))
            return pool

        mock_ladybug_pool = MagicMock()
        mock_ladybug_pool.startup = AsyncMock()

        # Mock initialize_ladybug_schema
        mock_init_schema = AsyncMock()
        monkeypatch.setattr(
            "modules.storage.ladybug.schema.initialize_ladybug_schema", mock_init_schema
        )

        monkeypatch.setattr("core.db.postgres.PostgresPool", lambda **kwargs: mock_pg_pool)
        monkeypatch.setattr("core.db.neo4j.Neo4jPool", mock_neo4j_fail)
        monkeypatch.setattr("core.db.ladybug_pool.LadybugPool", lambda **kwargs: mock_ladybug_pool)

        from core.db.strategy import create_strategy

        pg_settings = PostgresSettings(host="localhost", password="test")
        neo4j_settings = Neo4jSettings(enabled=True, uri="bolt://localhost:7687", password="test")
        ladybug_settings = LadybugSettings(enabled=True)

        strategy = await create_strategy(
            pg_settings=pg_settings,
            neo4j_settings=neo4j_settings,
            ladybug_settings=ladybug_settings,
        )

        assert strategy.relational_type == "postgresql"
        assert strategy.graph_type == "ladybug"
        mock_ladybug_pool.startup.assert_called_once()
        mock_init_schema.assert_called_once()
