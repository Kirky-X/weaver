# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for Cypher injection protection in graph visualization endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from api.endpoints.graph_visualization import SubgraphRequest


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
        with pytest.raises((TypeError, ValueError)):
            # This would fail at Pydantic validation level
            SubgraphRequest(
                center_entity="test",
                max_hops="1 OR 1=1",  # type: ignore[arg-type]
            )

    # ── Endpoint Boundary Validation Tests ────────────────────────────────

    @pytest.mark.asyncio
    async def test_endpoint_rejects_hops_out_of_range(self) -> None:
        """POST /graph/visualization endpoint should reject hops outside 1-4."""
        # hops=0 — rejected by Pydantic (Field constraint ge=1)
        with pytest.raises(ValidationError):
            SubgraphRequest(center_entity="test", max_hops=0)

        # hops=5 — rejected by Pydantic (Field constraint le=4)
        with pytest.raises(ValidationError):
            SubgraphRequest(center_entity="test", max_hops=5)

    @pytest.mark.asyncio
    async def test_endpoint_rejects_hops_above_max(self) -> None:
        """Very large hops values should be rejected."""
        with pytest.raises(ValidationError):
            SubgraphRequest(center_entity="test", max_hops=100)

    # ── Entity Name Handling Tests ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_entity_name_with_special_chars_in_request(self) -> None:
        """Entity names with special characters should be accepted in request model."""
        dangerous_name = "test'; MATCH (n) DELETE n; //"
        request = SubgraphRequest(center_entity=dangerous_name, max_hops=2)
        assert request.center_entity == dangerous_name

    @pytest.mark.asyncio
    async def test_entity_name_with_cypher_keywords_in_request(self) -> None:
        """Entity names containing Cypher keywords should be accepted in request model."""
        dangerous_name = "MATCH DELETE CREATE RETURN"
        request = SubgraphRequest(center_entity=dangerous_name, max_hops=2)
        assert request.center_entity == dangerous_name

    # ── Boundary Value Tests ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_hops_boundary_value_1(self) -> None:
        """hops=1 should be accepted."""
        request = SubgraphRequest(center_entity="test", max_hops=1)
        assert request.max_hops == 1

    @pytest.mark.asyncio
    async def test_hops_boundary_value_4(self) -> None:
        """hops=4 should be accepted."""
        request = SubgraphRequest(center_entity="test", max_hops=4)
        assert request.max_hops == 4

    # ── Integer Type Enforcement Tests ───────────────────────────────────────

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
