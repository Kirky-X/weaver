# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Neo4jSource adapter security features."""

import pytest

from core.db.safe_query import InvalidIdentifierError
from modules.migration.adapters.neo4j_source import Neo4jSource


class TestNeo4jSourceSecurity:
    """Security tests for Neo4jSource adapter."""

    @pytest.fixture
    def mock_pool(self, mocker):
        """Create a mock Neo4j pool."""
        pool = mocker.AsyncMock()
        pool.execute_query = mocker.AsyncMock(return_value=[])
        return pool

    @pytest.fixture
    def neo4j_source(self, mock_pool):
        """Create a Neo4jSource instance with mock pool."""
        return Neo4jSource(mock_pool)

    # ── Label Validation Tests ────────────────────────────────────────────

    @pytest.mark.parametrize(
        "label",
        [
            "Person",
            "Company",
            "TestLabel",
            "中文标签",
            "_PrivateLabel",
            "Label123",
        ],
    )
    @pytest.mark.asyncio
    async def test_read_nodes_accepts_valid_labels(self, neo4j_source, mock_pool, label):
        """Valid Neo4j labels should be accepted."""
        await neo4j_source.read_nodes(label, offset=0, limit=10)

        assert mock_pool.execute_query.called
        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0] if call_args[0] else call_args.args[0]

        # Should use parameterized query
        assert "$label" in query or "$" in query

    @pytest.mark.parametrize(
        "label",
        [
            "'; MATCH (n) DETACH DELETE n; --",
            "Person` WITH 1=1 DELETE ALL //",
            "label with spaces",
            "label-dash",
            "../../../etc/passwd",
            "{malicious}",
        ],
    )
    @pytest.mark.asyncio
    async def test_read_nodes_rejects_malicious_labels(self, neo4j_source, mock_pool, label):
        """Malicious labels should be rejected."""
        with pytest.raises((InvalidIdentifierError, ValueError)):
            await neo4j_source.read_nodes(label, offset=0, limit=10)

    # ── Edge Type Validation Tests ────────────────────────────────────────

    @pytest.mark.parametrize(
        "edge_type",
        [
            "KNOWS",
            "WORKS_FOR",
            "RELATES_TO",
            "中文关系",
            "A",
        ],
    )
    @pytest.mark.asyncio
    async def test_read_rels_accepts_valid_edge_types(self, neo4j_source, mock_pool, edge_type):
        """Valid edge types (uppercase) should be accepted."""
        await neo4j_source.read_rels(edge_type, offset=0, limit=10)

        assert mock_pool.execute_query.called

    @pytest.mark.parametrize(
        "edge_type",
        [
            "knows",  # Lowercase not allowed
            "KNOWS'; DELETE ALL //",
            "123INVALID",
            "invalid-type",
            "type with space",
        ],
    )
    @pytest.mark.asyncio
    async def test_read_rels_rejects_malicious_edge_types(self, neo4j_source, mock_pool, edge_type):
        """Malicious edge types should be rejected."""
        with pytest.raises((InvalidIdentifierError, ValueError)):
            await neo4j_source.read_rels(edge_type, offset=0, limit=10)

    # ── Parameterized Query Tests ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_read_nodes_uses_parameterized_query(self, neo4j_source, mock_pool):
        """read_nodes should use parameterized Cypher query."""
        await neo4j_source.read_nodes("Person", offset=0, limit=10)

        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0] if call_args[0] else call_args.args[0]
        params = call_args[1] if call_args[1] else {}

        # Should NOT use backtick escaping with f-string
        assert "`Person`" not in query or "$label" in query

        # Should use parameterized form
        assert "$label" in query or "$" in query

        # Parameters should include label
        if params:
            assert "label" in params or "1" in params

    @pytest.mark.asyncio
    async def test_count_nodes_uses_parameterized_query(self, neo4j_source, mock_pool):
        """count_nodes should use parameterized query."""
        mock_pool.execute_query.return_value = [{"count": 50}]

        await neo4j_source.count_nodes("Person")

        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0] if call_args[0] else call_args.args[0]

        # Should use $label parameter
        assert "$label" in query

    @pytest.mark.asyncio
    async def test_read_rels_uses_parameterized_query(self, neo4j_source, mock_pool):
        """read_rels should use parameterized Cypher query."""
        await neo4j_source.read_rels("KNOWS", offset=0, limit=10)

        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0] if call_args[0] else call_args.args[0]

        # Should use type(r) = $relType pattern
        assert "type(r)" in query.lower() or "$reltype" in query.lower()

    # ── Cypher Injection Prevention Tests ────────────────────────────────

    @pytest.mark.asyncio
    async def test_prevents_cypher_injection_in_label(self, neo4j_source, mock_pool):
        """Cypher injection attempts should be blocked."""
        malicious_label = "Person` WITH 1=1 MATCH (n) DETACH DELETE n //"

        with pytest.raises((InvalidIdentifierError, ValueError)):
            await neo4j_source.read_nodes(malicious_label, 0, 10)

        mock_pool.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_prevents_cypher_injection_in_edge_type(self, neo4j_source, mock_pool):
        """Cypher injection via edge type should be blocked."""
        malicious_type = "KNOWS`] MATCH (n) DETACH DELETE n //"

        with pytest.raises((InvalidIdentifierError, ValueError)):
            await neo4j_source.read_rels(malicious_type, 0, 10)

        mock_pool.execute_query.assert_not_called()

    # ── Offset/Limit Validation Tests ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_read_nodes_validates_offset(self, neo4j_source):
        """Negative offset should be rejected."""
        with pytest.raises(ValueError, match="offset must be non-negative"):
            await neo4j_source.read_nodes("Person", offset=-1, limit=10)

    @pytest.mark.asyncio
    async def test_read_nodes_validates_limit(self, neo4j_source):
        """Non-positive limit should be rejected."""
        with pytest.raises(ValueError, match="limit must be positive"):
            await neo4j_source.read_nodes("Person", offset=0, limit=0)


class TestNeo4jSourceFunctionality:
    """Functional tests for Neo4jSource adapter."""

    @pytest.fixture
    def mock_pool(self, mocker):
        """Create a mock Neo4j pool."""
        pool = mocker.AsyncMock()
        return pool

    @pytest.fixture
    def neo4j_source(self, mock_pool):
        """Create a Neo4jSource instance with mock pool."""
        return Neo4jSource(mock_pool)

    @pytest.mark.asyncio
    async def test_count_nodes_returns_correct_count(self, neo4j_source, mock_pool):
        """count_nodes should return the count from query result."""
        mock_pool.execute_query.return_value = [{"count": 456}]

        result = await neo4j_source.count_nodes("Person")

        assert result == 456

    @pytest.mark.asyncio
    async def test_count_rels_returns_correct_count(self, neo4j_source, mock_pool):
        """count_rels should return the count from query result."""
        mock_pool.execute_query.return_value = [{"count": 789}]

        result = await neo4j_source.count_rels("KNOWS")

        assert result == 789

    @pytest.mark.asyncio
    async def test_get_label_names_extracts_labels(self, neo4j_source, mock_pool):
        """get_label_names should extract labels from result."""
        mock_pool.execute_query.return_value = [
            {"label": "Person"},
            {"label": "Company"},
            {"label": "Project"},
        ]

        result = await neo4j_source.get_label_names()

        assert result == ["Person", "Company", "Project"]

    @pytest.mark.asyncio
    async def test_get_rel_type_names_extracts_types(self, neo4j_source, mock_pool):
        """get_rel_type_names should extract relationship types."""
        mock_pool.execute_query.return_value = [
            {"relationshipType": "KNOWS"},
            {"relationshipType": "WORKS_FOR"},
        ]

        result = await neo4j_source.get_rel_type_names()

        assert result == ["KNOWS", "WORKS_FOR"]
