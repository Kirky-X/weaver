# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for pool protocol definitions."""

from typing import Protocol, runtime_checkable

import pytest

from core.protocols import GraphPool, RelationalPool


class MockRelationalPool:
    """Mock implementation of RelationalPool for testing."""

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    @property
    def engine(self):
        return "mock_engine"

    def session(self):
        return "mock_session"

    async def session_context(self):
        yield "mock_session"


class MockGraphPool:
    """Mock implementation of GraphPool for testing."""

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def execute_query(self, query: str, parameters: dict | None = None):
        return [{"result": "ok"}]

    async def session_context(self):
        yield "mock_session"


class TestRelationalPoolProtocol:
    """Tests for RelationalPool protocol."""

    def test_is_protocol(self) -> None:
        """RelationalPool should be a Protocol."""
        assert issubclass(RelationalPool, Protocol)

    def test_decorated_with_runtime_checkable(self) -> None:
        """RelationalPool should be decorated with @runtime_checkable."""
        # Check that isinstance() works with non-matching classes
        # This proves @runtime_checkable was applied
        assert isinstance(object(), RelationalPool) is False

    def test_mock_satisfies_protocol(self) -> None:
        """MockRelationalPool should satisfy RelationalPool protocol."""
        mock = MockRelationalPool()
        assert isinstance(mock, RelationalPool)

    def test_missing_methods_not_instance(self) -> None:
        """Class missing required methods should not satisfy protocol."""

        class IncompletePool:
            async def startup(self) -> None:
                pass

        incomplete = IncompletePool()
        # Protocol checking at runtime
        assert not isinstance(incomplete, RelationalPool)


class TestGraphPoolProtocol:
    """Tests for GraphPool protocol."""

    def test_is_protocol(self) -> None:
        """GraphPool should be a Protocol."""
        assert issubclass(GraphPool, Protocol)

    def test_decorated_with_runtime_checkable(self) -> None:
        """GraphPool should be decorated with @runtime_checkable."""
        # Check that isinstance() works with non-matching classes
        assert isinstance(object(), GraphPool) is False

    def test_mock_satisfies_protocol(self) -> None:
        """MockGraphPool should satisfy GraphPool protocol."""
        mock = MockGraphPool()
        assert isinstance(mock, GraphPool)

    def test_missing_methods_not_instance(self) -> None:
        """Class missing required methods should not satisfy protocol."""

        class IncompletePool:
            async def startup(self) -> None:
                pass

        incomplete = IncompletePool()
        assert not isinstance(incomplete, GraphPool)
