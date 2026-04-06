# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LadybugSource adapter security features."""

import pytest

from core.db.safe_query import InvalidIdentifierError
from modules.migration.adapters.ladybug_source import LadybugSource


class TestLadybugSourceSecurity:
    """Security tests for LadybugSource adapter."""

    @pytest.fixture
    def mock_pool(self, mocker):
        """Create a mock LadybugDB pool."""
        pool = mocker.AsyncMock()
        pool.execute_query = mocker.AsyncMock(return_value=[])
        return pool

    @pytest.fixture
    def ladybug_source(self, mock_pool):
        """Create a LadybugSource instance with mock pool."""
        return LadybugSource(mock_pool)

    # ── Input Validation Tests ───────────────────────────────────────────

    @pytest.mark.parametrize(
        "label",
        [
            "valid_label",
            "ValidLabel",
            "label123",
            "_private_label",
        ],
    )
    @pytest.mark.asyncio
    async def test_read_nodes_accepts_valid_labels(self, ladybug_source, mock_pool, label):
        """Valid labels should be accepted."""
        await ladybug_source.read_nodes(label, offset=0, limit=10)

        # Verify query was executed (pool called)
        assert mock_pool.execute_query.called
        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0] if call_args[0] else call_args.args[0]

        # Query should use parameterized form, not f-string
        assert "$1" in query or "WHERE label = $1" in query

    @pytest.mark.parametrize(
        "label",
        [
            "'; DROP TABLE nodes; --",
            "label'; DELETE FROM nodes WHERE '1'='1",
            "invalid-label-with-dash",
            "label with spaces",
            "label; DROP TABLE",
            "../../../etc/passwd",
        ],
    )
    @pytest.mark.asyncio
    async def test_read_nodes_rejects_malicious_labels(self, ladybug_source, label):
        """Malicious labels should be rejected with validation error."""
        with pytest.raises((InvalidIdentifierError, ValueError)):
            await ladybug_source.read_nodes(label, offset=0, limit=10)

    @pytest.mark.asyncio
    async def test_read_nodes_validates_offset(self, ladybug_source):
        """Negative offset should be rejected."""
        with pytest.raises(ValueError, match="offset must be non-negative"):
            await ladybug_source.read_nodes("valid_label", offset=-1, limit=10)

    @pytest.mark.asyncio
    async def test_read_nodes_validates_limit(self, ladybug_source):
        """Non-positive limit should be rejected."""
        with pytest.raises(ValueError, match="limit must be positive"):
            await ladybug_source.read_nodes("valid_label", offset=0, limit=0)

        with pytest.raises(ValueError, match="limit must be positive"):
            await ladybug_source.read_nodes("valid_label", offset=0, limit=-5)

    # ── Parameterized Query Tests ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_count_nodes_uses_parameterized_query(self, ladybug_source, mock_pool):
        """count_nodes should use parameterized query, not f-string."""
        mock_pool.execute_query.return_value = [{"count": 42}]

        await ladybug_source.count_nodes("test_label")

        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0] if call_args[0] else call_args.args[0]

        # Should NOT contain f-string interpolation like '{label}'
        assert "{label}" not in query
        assert "f'" not in query and 'f"' not in query

        # Should use parameterized query
        assert "$1" in query

    @pytest.mark.asyncio
    async def test_read_rels_uses_parameterized_query(self, ladybug_source, mock_pool):
        """read_rels should use parameterized query."""
        await ladybug_source.read_rels("RELATES_TO", offset=0, limit=10)

        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0] if call_args[0] else call_args.args[0]

        # Should use parameters
        assert "$1" in query or "$2" in query

    # ── SQL Injection Prevention Tests ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_prevents_sql_injection_in_label(self, ladybug_source, mock_pool):
        """SQL injection attempts in label should be blocked before query."""
        malicious_label = "'; DROP TABLE nodes; --"

        with pytest.raises((InvalidIdentifierError, ValueError)):
            await ladybug_source.read_nodes(malicious_label, 0, 10)

        # Query should not have been executed
        mock_pool.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_prevents_sql_injection_in_rel_type(self, ladybug_source, mock_pool):
        """SQL injection attempts in rel_type should be blocked."""
        malicious_type = "'; DELETE FROM edges WHERE '1'='1"

        with pytest.raises((InvalidIdentifierError, ValueError)):
            await ladybug_source.read_rels(malicious_type, 0, 10)

        mock_pool.execute_query.assert_not_called()


class TestLadybugSourceFunctionality:
    """Functional tests for LadybugSource adapter."""

    @pytest.fixture
    def mock_pool(self, mocker):
        """Create a mock LadybugDB pool."""
        pool = mocker.AsyncMock()
        return pool

    @pytest.fixture
    def ladybug_source(self, mock_pool):
        """Create a LadybugSource instance with mock pool."""
        return LadybugSource(mock_pool)

    @pytest.mark.asyncio
    async def test_count_nodes_returns_correct_count(self, ladybug_source, mock_pool):
        """count_nodes should return the count from query result."""
        mock_pool.execute_query.return_value = [{"count": 123}]

        result = await ladybug_source.count_nodes("Person")

        assert result == 123

    @pytest.mark.asyncio
    async def test_count_nodes_returns_zero_on_empty_result(self, ladybug_source, mock_pool):
        """count_nodes should return 0 if no results."""
        mock_pool.execute_query.return_value = []

        result = await ladybug_source.count_nodes("Person")

        assert result == 0

    @pytest.mark.asyncio
    async def test_get_label_names_returns_distinct_labels(self, ladybug_source, mock_pool):
        """get_label_names should return list of distinct labels."""
        mock_pool.execute_query.return_value = [
            {"label": "Person"},
            {"label": "Company"},
            {"label": "Project"},
        ]

        result = await ladybug_source.get_label_names()

        assert result == ["Person", "Company", "Project"]
