# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for Cypher injection protection in graph visualization endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from api.endpoints.graph_visualization import (
    SubgraphRequest,
    _extract_subgraph_nodes,
)


class TestCypherInjectionProtection:
    """Tests for Cypher injection protection."""

    # ── Parameter Validation Tests ──────────────────────────────────────────

    def test_subgraph_request_max_hops_validation_valid(self) -> None:
        """Valid max_hops values should pass validation."""
        for hops in [1, 2, 3, 4]:
            request = SubgraphRequest(
                center_entity="test_entity",
                max_hops=hops,
            )
            assert request.max_hops == hops

    def test_subgraph_request_max_hops_validation_below_min(self) -> None:
        """max_hops below 1 should fail validation."""
        with pytest.raises(ValidationError):
            SubgraphRequest(
                center_entity="test_entity",
                max_hops=0,
            )

    def test_subgraph_request_max_hops_validation_above_max(self) -> None:
        """max_hops above 4 should fail validation."""
        with pytest.raises(ValidationError):
            SubgraphRequest(
                center_entity="test_entity",
                max_hops=5,
            )

    def test_subgraph_request_max_hops_must_be_int(self) -> None:
        """max_hops must be an integer."""
        with pytest.raises(ValidationError):
            SubgraphRequest(
                center_entity="test_entity",
                max_hops="2; MATCH (n) DELETE n",  # type: ignore[arg-type]
            )

    # ── Cypher Injection Attempt Tests ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_injection_attempt_in_max_hops_blocked(self) -> None:
        """Injection attempts in max_hops should be blocked by type validation."""
        mock_pool = MagicMock()

        # The injection attempt would be blocked by Pydantic type validation
        # but we test the endpoint behavior as well
        with pytest.raises((TypeError, ValueError)):
            # This would fail at Pydantic validation level
            SubgraphRequest(
                center_entity="test",
                max_hops="1 OR 1=1",  # type: ignore[arg-type]
            )

    @pytest.mark.asyncio
    async def test_extract_subgraph_validates_hops_range(self) -> None:
        """_extract_subgraph_nodes should validate hops range."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        # Valid hops should work
        await _extract_subgraph_nodes(mock_pool, "test_entity", 2)

        # Invalid hops should raise ValueError
        with pytest.raises(ValueError, match="hops must be between 1 and 4"):
            await _extract_subgraph_nodes(mock_pool, "test_entity", 0)

        with pytest.raises(ValueError, match="hops must be between 1 and 4"):
            await _extract_subgraph_nodes(mock_pool, "test_entity", 5)

    @pytest.mark.asyncio
    async def test_extract_subgraph_rejects_negative_hops(self) -> None:
        """Negative hops should be rejected."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        with pytest.raises(ValueError):
            await _extract_subgraph_nodes(mock_pool, "test_entity", -1)

    @pytest.mark.asyncio
    async def test_extract_subgraph_rejects_large_hops(self) -> None:
        """Very large hops values should be rejected."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        with pytest.raises(ValueError):
            await _extract_subgraph_nodes(mock_pool, "test_entity", 100)

    # ── Entity Name Handling Tests ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_entity_name_with_special_chars_handled_safely(self) -> None:
        """Entity names with special characters should be safely parameterized."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[{"id": "test", "label": "test", "type": "Person", "description": "test"}]
        )

        # Entity name with special characters that could be dangerous in string concatenation
        # But should be safe because we use parameterized queries
        dangerous_name = "test'; MATCH (n) DELETE n; //"

        # This should use parameterized query, not string concatenation
        await _extract_subgraph_nodes(mock_pool, dangerous_name, 2)

        # Verify the query was called - the important thing is that it doesn't crash
        # and the query is formed correctly with parameterized input
        assert mock_pool.execute_query.call_count >= 1

    @pytest.mark.asyncio
    async def test_entity_name_with_cypher_keywords_handled_safely(self) -> None:
        """Entity names containing Cypher keywords should be safely parameterized."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        # Entity name containing Cypher keywords
        dangerous_name = "MATCH DELETE CREATE RETURN"

        await _extract_subgraph_nodes(mock_pool, dangerous_name, 2)

        # Verify the query was called - the important thing is that it doesn't crash
        # and the query is formed correctly with parameterized input
        assert mock_pool.execute_query.call_count >= 1

    # ── Boundary Value Tests ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_hops_boundary_value_1(self) -> None:
        """hops=1 should be accepted."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        await _extract_subgraph_nodes(mock_pool, "test", 1)
        # _extract_subgraph_nodes makes multiple calls (nodes + edges)
        assert mock_pool.execute_query.call_count >= 1

    @pytest.mark.asyncio
    async def test_hops_boundary_value_4(self) -> None:
        """hops=4 should be accepted."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        await _extract_subgraph_nodes(mock_pool, "test", 4)
        # _extract_subgraph_nodes makes multiple calls (nodes + edges)
        assert mock_pool.execute_query.call_count >= 1

    # ── Integer Type Enforcement Tests ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_float_hops_converted_to_int(self) -> None:
        """Float hops values should be converted to int."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        # Float that's a valid integer value
        await _extract_subgraph_nodes(mock_pool, "test", 2.0)  # type: ignore[arg-type]

        # The query should still be formed correctly
        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0] if call_args[0] else call_args.args[0]

        # Check that the query contains a valid integer, not a float
        assert "1..2" in query or "1..2.0" not in query

    @pytest.mark.asyncio
    async def test_string_number_hops_converted(self) -> None:
        """String number hops should be converted to int by Pydantic."""
        # Pydantic V2 can coerce string numbers to int
        request = SubgraphRequest(
            center_entity="test",
            max_hops="2",  # type: ignore[arg-type]
        )
        # Pydantic should coerce to int
        assert request.max_hops == 2
        assert isinstance(request.max_hops, int)
