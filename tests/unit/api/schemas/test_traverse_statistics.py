# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for TraverseResponse statistics field."""

from __future__ import annotations

from api.schemas.traverse import TraverseResponse, TraverseStatistics


class TestTraverseStatistics:
    """Tests for TraverseStatistics model."""

    def test_statistics_has_required_fields(self) -> None:
        """TraverseStatistics SHALL contain nodes_visited, edges_traversed, depth_reached."""
        stats = TraverseStatistics(
            nodes_visited=10,
            edges_traversed=8,
            depth_reached=3,
        )
        assert stats.nodes_visited == 10
        assert stats.edges_traversed == 8
        assert stats.depth_reached == 3

    def test_statistics_optional_fields(self) -> None:
        """TraverseStatistics SHALL support optional execution_time_ms."""
        stats = TraverseStatistics(
            nodes_visited=5,
            edges_traversed=3,
            depth_reached=2,
            execution_time_ms=150,
        )
        assert stats.execution_time_ms == 150

    def test_statistics_defaults(self) -> None:
        """TraverseStatistics optional fields default to None."""
        stats = TraverseStatistics(
            nodes_visited=0,
            edges_traversed=0,
            depth_reached=0,
        )
        assert stats.execution_time_ms is None


class TestTraverseResponseStatistics:
    """Tests for TraverseResponse with statistics field."""

    def test_response_has_statistics_field(self) -> None:
        """TraverseResponse SHALL contain a top-level statistics field."""
        stats = TraverseStatistics(
            nodes_visited=10,
            edges_traversed=8,
            depth_reached=3,
        )
        response = TraverseResponse(
            results=[],
            statistics=stats,
        )
        assert response.statistics is not None
        assert response.statistics.nodes_visited == 10
        assert response.statistics.edges_traversed == 8
        assert response.statistics.depth_reached == 3

    def test_response_statistics_defaults_to_zero(self) -> None:
        """TraverseResponse statistics SHALL default to zero values."""
        response = TraverseResponse(results=[])
        assert response.statistics is not None
        assert response.statistics.nodes_visited == 0
        assert response.statistics.edges_traversed == 0
        assert response.statistics.depth_reached == 0

    def test_response_serialization_includes_statistics(self) -> None:
        """TraverseResponse JSON serialization SHALL include statistics."""
        stats = TraverseStatistics(
            nodes_visited=5,
            edges_traversed=3,
            depth_reached=2,
            execution_time_ms=100,
        )
        response = TraverseResponse(results=[], statistics=stats)
        data = response.model_dump()
        assert "statistics" in data
        assert data["statistics"]["nodes_visited"] == 5
        assert data["statistics"]["edges_traversed"] == 3
        assert data["statistics"]["depth_reached"] == 2
        assert data["statistics"]["execution_time_ms"] == 100
