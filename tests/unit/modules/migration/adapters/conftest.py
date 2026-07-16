# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Shared fixtures for migration adapter tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def duckdb_mock_pool():
    """Create a mock DuckDB pool with _engine attribute."""
    mock_pool = MagicMock()
    mock_pool._engine = MagicMock()
    return mock_pool


@pytest.fixture
def postgres_mock_pool():
    """Create a mock PostgreSQL pool with engine attribute."""
    mock_pool = MagicMock()
    mock_pool.engine = MagicMock()
    return mock_pool


@pytest.fixture
def graph_mock_pool():
    """Create a mock graph DB pool (Neo4j/Ladybug) with async interface."""
    mock_pool = AsyncMock()
    mock_pool.execute_query = AsyncMock(return_value=[])
    return mock_pool


@pytest.fixture
def postgres_async_conn():
    """Create a mock async PostgreSQL connection with standard query result."""
    mock_conn = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 100
    mock_result.fetchall.return_value = []
    mock_conn.execute.return_value = mock_result
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    return mock_conn
