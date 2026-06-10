# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for ConsolidationWorker SchemaNode clustering.

Tests for:
- Event clustering by type and participants
- Minimum 3 events per cluster
- SchemaNode creation from clusters
- SchemaNode attributes (event_type, pattern, confidence)
- Stale event marking after 90 days
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.core.schema_node import SchemaNode
from modules.memory.evolution.slow_path import StructuralConsolidationWorker


class TestClusterByTypeAndParticipants:
    """Tests for clustering events by type and participants."""

    @pytest.fixture
    def worker(self):
        return StructuralConsolidationWorker(
            temporal_repo=MagicMock(),
            causal_repo=MagicMock(),
            consolidation_queue=MagicMock(),
            llm_client=MagicMock(),
        )

    def test_cluster_by_type_and_participants(self, worker):
        """Cluster events that share the same type and participants."""
        events = [
            {
                "id": "e1",
                "event_type": "military_conflict",
                "participants": ["entity_a", "entity_b"],
                "content": "Conflict between A and B",
            },
            {
                "id": "e2",
                "event_type": "military_conflict",
                "participants": ["entity_a", "entity_b"],
                "content": "Another conflict between A and B",
            },
            {
                "id": "e3",
                "event_type": "military_conflict",
                "participants": ["entity_a", "entity_b"],
                "content": "Yet another conflict between A and B",
            },
            {
                "id": "e4",
                "event_type": "election",
                "participants": ["entity_c"],
                "content": "Election in C",
            },
        ]

        clusters = worker._cluster_by_type_and_participants(events)

        assert len(clusters) >= 1
        # The military_conflict cluster should have 3 events
        military_clusters = [c for c in clusters if c["event_type"] == "military_conflict"]
        assert len(military_clusters) == 1
        assert len(military_clusters[0]["events"]) == 3

    def test_cluster_different_types_separate(self, worker):
        """Events of different types should not be in the same cluster."""
        events = [
            {"id": "e1", "event_type": "type_a", "participants": ["x"], "content": "A"},
            {"id": "e2", "event_type": "type_b", "participants": ["x"], "content": "B"},
        ]

        clusters = worker._cluster_by_type_and_participants(events)

        # Should not form any cluster (minimum 3 events)
        assert len(clusters) == 0


class TestClusterMinimum3Events:
    """Tests for minimum cluster size requirement."""

    @pytest.fixture
    def worker(self):
        return StructuralConsolidationWorker(
            temporal_repo=MagicMock(),
            causal_repo=MagicMock(),
            consolidation_queue=MagicMock(),
            llm_client=MagicMock(),
        )

    def test_cluster_minimum_3_events(self, worker):
        """Clusters with fewer than 3 events should be discarded."""
        events = [
            {
                "id": "e1",
                "event_type": "trade_deal",
                "participants": ["a", "b"],
                "content": "Trade deal 1",
            },
            {
                "id": "e2",
                "event_type": "trade_deal",
                "participants": ["a", "b"],
                "content": "Trade deal 2",
            },
        ]

        clusters = worker._cluster_by_type_and_participants(events)

        # Only 2 events — below minimum of 3
        assert len(clusters) == 0

    def test_cluster_exactly_3_events(self, worker):
        """A cluster with exactly 3 events should be accepted."""
        events = [
            {
                "id": f"e{i}",
                "event_type": "trade_deal",
                "participants": ["a", "b"],
                "content": f"Trade deal {i}",
            }
            for i in range(3)
        ]

        clusters = worker._cluster_by_type_and_participants(events)

        assert len(clusters) == 1
        assert len(clusters[0]["events"]) == 3


class TestUpdateSchemaCreatesSchemaNode:
    """Tests for SchemaNode creation from event clusters."""

    @pytest.fixture
    def worker(self):
        return StructuralConsolidationWorker(
            temporal_repo=MagicMock(),
            causal_repo=MagicMock(),
            consolidation_queue=MagicMock(),
            llm_client=MagicMock(),
        )

    def test_update_schema_creates_schema_node(self, worker):
        """_update_schema should create a SchemaNode from a cluster."""
        cluster = {
            "event_type": "military_conflict",
            "participants": ["entity_a", "entity_b"],
            "events": [
                {"id": "e1", "content": "Conflict 1"},
                {"id": "e2", "content": "Conflict 2"},
                {"id": "e3", "content": "Conflict 3"},
            ],
        }

        schema_node = worker._update_schema(cluster)

        assert isinstance(schema_node, SchemaNode)
        assert schema_node.event_type == "military_conflict"
        assert schema_node.confidence > 0.0

    def test_update_schema_multiple_clusters(self, worker):
        """Multiple clusters should produce multiple SchemaNodes."""
        clusters = [
            {
                "event_type": "military_conflict",
                "participants": ["a", "b"],
                "events": [
                    {"id": "e1", "content": "C1"},
                    {"id": "e2", "content": "C2"},
                    {"id": "e3", "content": "C3"},
                ],
            },
            {
                "event_type": "election",
                "participants": ["c"],
                "events": [
                    {"id": "e4", "content": "E1"},
                    {"id": "e5", "content": "E2"},
                    {"id": "e6", "content": "E3"},
                ],
            },
        ]

        schema_nodes = [worker._update_schema(c) for c in clusters]

        assert len(schema_nodes) == 2
        assert schema_nodes[0].event_type == "military_conflict"
        assert schema_nodes[1].event_type == "election"


class TestSchemaNodeHasEventTypePatternConfidence:
    """Tests for SchemaNode attributes."""

    def test_schema_node_attributes(self):
        """SchemaNode must have event_type, pattern, and confidence."""
        node = SchemaNode(
            id="schema-1",
            event_type="military_conflict",
            pattern="entity_a_vs_entity_b",
            confidence=0.85,
        )

        assert node.id == "schema-1"
        assert node.event_type == "military_conflict"
        assert node.pattern == "entity_a_vs_entity_b"
        assert node.confidence == 0.85

    def test_schema_node_frozen(self):
        """SchemaNode should be immutable (frozen dataclass)."""
        node = SchemaNode(
            id="schema-1",
            event_type="election",
            pattern="democratic_process",
            confidence=0.9,
        )

        with pytest.raises(AttributeError):
            node.confidence = 0.5

    def test_schema_node_confidence_range(self):
        """SchemaNode confidence should be between 0.0 and 1.0."""
        node = SchemaNode(
            id="schema-2",
            event_type="trade_deal",
            pattern="bilateral",
            confidence=0.75,
        )

        assert 0.0 <= node.confidence <= 1.0


class TestMarkStaleEventsAfter90Days:
    """Tests for marking events as stale after 90 days."""

    @pytest.fixture
    def worker(self):
        return StructuralConsolidationWorker(
            temporal_repo=MagicMock(),
            causal_repo=MagicMock(),
            consolidation_queue=MagicMock(),
            llm_client=MagicMock(),
        )

    def test_mark_stale_events_90_days(self, worker):
        """Events not accessed in 90+ days should be marked stale."""
        now = datetime.now(UTC)
        old_date = now - timedelta(days=100)
        recent_date = now - timedelta(days=10)

        events = [
            {"id": "e1", "last_accessed": old_date.isoformat(), "stale": False},
            {"id": "e2", "last_accessed": recent_date.isoformat(), "stale": False},
        ]

        result = worker._mark_stale_events(events)

        stale_ids = [e["id"] for e in result if e.get("stale")]
        assert "e1" in stale_ids
        assert "e2" not in stale_ids

    def test_mark_stale_events_exactly_90_days(self, worker):
        """Events accessed exactly 90 days ago should be marked stale."""
        now = datetime.now(UTC)
        boundary_date = now - timedelta(days=90)

        events = [
            {"id": "e1", "last_accessed": boundary_date.isoformat(), "stale": False},
        ]

        result = worker._mark_stale_events(events)

        assert result[0]["stale"] is True

    def test_mark_stale_events_recent_not_stale(self, worker):
        """Events accessed within 90 days should not be marked stale."""
        now = datetime.now(UTC)
        recent_date = now - timedelta(days=30)

        events = [
            {"id": "e1", "last_accessed": recent_date.isoformat(), "stale": False},
        ]

        result = worker._mark_stale_events(events)

        assert result[0]["stale"] is False
