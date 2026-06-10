# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for event-centric KG relationship upgrades.

Tests for:
- HAS_PARTICIPANT(role) relationship between Event and Entity
- HAS_SUB_EVENT relationship between parent and child Events
- HAS_NARRATIVE relationship between Event and Narrative
- Narrative node attributes (source_bias, frame, tone, emphasis)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.core.event_node import EventNode
from modules.memory.core.narrative_node import NarrativeNode
from modules.memory.graphs.event import EventGraphRepo


class TestAddParticipantWithRole:
    """Tests for HAS_PARTICIPANT relationship with role attribute."""

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.database_type = "neo4j"
        pool.execute_query = AsyncMock(
            return_value=[{"event_id": "e1", "entity_id": "ent1", "role": "initiator"}]
        )
        return pool

    @pytest.mark.asyncio
    async def test_add_participant_stores_role_attribute(self, mock_pool):
        """HAS_PARTICIPANT must contain role attribute (initiator/target/observer/beneficiary)."""
        repo = EventGraphRepo(pool=mock_pool)

        result = await repo.add_participant(event_id="e1", entity_id="ent1", role="initiator")

        assert result is True
        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0]
        params = call_args[0][1]

        assert "HAS_PARTICIPANT" in query
        assert params["role"] == "initiator"
        assert params["event_id"] == "e1"
        assert params["entity_id"] == "ent1"

    @pytest.mark.asyncio
    async def test_add_participant_all_roles(self, mock_pool):
        """All valid roles should be accepted."""
        repo = EventGraphRepo(pool=mock_pool)

        for role in ("initiator", "target", "observer", "beneficiary"):
            result = await repo.add_participant(event_id="e1", entity_id="ent1", role=role)
            assert result is True

    @pytest.mark.asyncio
    async def test_add_participant_ladybug_backend(self):
        """HAS_PARTICIPANT must work with LadybugDB backend."""
        pool = MagicMock()
        pool.database_type = "ladybug"
        pool.execute_query = AsyncMock(return_value=[{"event_id": "e1", "entity_id": "ent1"}])

        repo = EventGraphRepo(pool=pool)
        result = await repo.add_participant(event_id="e1", entity_id="ent1", role="target")

        assert result is True
        call_args = pool.execute_query.call_args
        query = call_args[0][0]
        assert "HAS_PARTICIPANT" in query

    @pytest.mark.asyncio
    async def test_add_participant_failure(self, mock_pool):
        """add_participant returns False on DB failure."""
        mock_pool.execute_query = AsyncMock(side_effect=Exception("DB error"))

        repo = EventGraphRepo(pool=mock_pool)
        result = await repo.add_participant(event_id="e1", entity_id="ent1", role="initiator")

        assert result is False


class TestAddSubEvent:
    """Tests for HAS_SUB_EVENT relationship between parent and child events."""

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.database_type = "neo4j"
        pool.execute_query = AsyncMock(return_value=[{"parent_id": "e1", "child_id": "e2"}])
        return pool

    @pytest.mark.asyncio
    async def test_add_sub_event_connects_parent_and_child(self, mock_pool):
        """HAS_SUB_EVENT connects parent and child events."""
        repo = EventGraphRepo(pool=mock_pool)

        result = await repo.add_sub_event(parent_id="e1", child_id="e2")

        assert result is True
        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0]
        params = call_args[0][1]

        assert "HAS_SUB_EVENT" in query
        assert params["parent_id"] == "e1"
        assert params["child_id"] == "e2"

    @pytest.mark.asyncio
    async def test_add_sub_event_ladybug_backend(self):
        """HAS_SUB_EVENT must work with LadybugDB backend."""
        pool = MagicMock()
        pool.database_type = "ladybug"
        pool.execute_query = AsyncMock(return_value=[{"parent_id": "e1", "child_id": "e2"}])

        repo = EventGraphRepo(pool=pool)
        result = await repo.add_sub_event(parent_id="e1", child_id="e2")

        assert result is True
        call_args = pool.execute_query.call_args
        query = call_args[0][0]
        assert "HAS_SUB_EVENT" in query


class TestAddNarrative:
    """Tests for HAS_NARRATIVE relationship between Event and Narrative."""

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.database_type = "neo4j"
        pool.execute_query = AsyncMock(return_value=[{"event_id": "e1", "narrative_id": "n1"}])
        return pool

    @pytest.mark.asyncio
    async def test_add_narrative_connects_event_to_narrative(self, mock_pool):
        """HAS_NARRATIVE connects event to narrative node."""
        repo = EventGraphRepo(pool=mock_pool)

        narrative = NarrativeNode(
            id="n1",
            source_bias="left",
            frame="economic_impact",
            tone="critical",
            emphasis="inequality",
        )

        result = await repo.add_narrative(event_id="e1", narrative=narrative)

        assert result is True
        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0]
        params = call_args[0][1]

        assert "HAS_NARRATIVE" in query
        assert params["event_id"] == "e1"
        assert params["narrative_id"] == "n1"
        assert params["source_bias"] == "left"
        assert params["frame"] == "economic_impact"
        assert params["tone"] == "critical"
        assert params["emphasis"] == "inequality"

    @pytest.mark.asyncio
    async def test_add_narrative_ladybug_backend(self):
        """HAS_NARRATIVE must work with LadybugDB backend."""
        pool = MagicMock()
        pool.database_type = "ladybug"
        pool.execute_query = AsyncMock(return_value=[{"event_id": "e1", "narrative_id": "n1"}])

        repo = EventGraphRepo(pool=pool)
        narrative = NarrativeNode(
            id="n1", source_bias="center", frame="political", tone="neutral", emphasis="policy"
        )

        result = await repo.add_narrative(event_id="e1", narrative=narrative)

        assert result is True


class TestGetEventParticipantsByRole:
    """Tests for querying participants by role."""

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.database_type = "neo4j"
        pool.execute_query = AsyncMock(
            return_value=[
                {"entity_id": "ent1", "role": "initiator"},
                {"entity_id": "ent2", "role": "target"},
            ]
        )
        return pool

    @pytest.mark.asyncio
    async def test_get_participants_by_role(self, mock_pool):
        """Query participants filtered by role."""
        repo = EventGraphRepo(pool=mock_pool)

        result = await repo.get_participants(event_id="e1", role="initiator")

        assert len(result) >= 1
        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0]
        assert "HAS_PARTICIPANT" in query

    @pytest.mark.asyncio
    async def test_get_participants_all_roles(self, mock_pool):
        """Query all participants without role filter."""
        repo = EventGraphRepo(pool=mock_pool)

        result = await repo.get_participants(event_id="e1")

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_participants_ladybug_backend(self):
        """get_participants must work with LadybugDB backend using r.edge_type."""
        pool = MagicMock()
        pool.database_type = "ladybug"
        pool.execute_query = AsyncMock(
            return_value=[
                {"entity_id": "ent1", "role": "initiator"},
            ]
        )

        repo = EventGraphRepo(pool=pool)
        result = await repo.get_participants(event_id="e1", role="initiator")

        assert len(result) >= 1


class TestGetSubEventsRecursive:
    """Tests for recursively getting sub-events."""

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.database_type = "neo4j"
        pool.execute_query = AsyncMock(
            return_value=[
                {"id": "e2", "content": "sub-event 1"},
                {"id": "e3", "content": "sub-event 2"},
            ]
        )
        return pool

    @pytest.mark.asyncio
    async def test_get_sub_events_recursive(self, mock_pool):
        """Recursively get sub-events up to max_depth."""
        repo = EventGraphRepo(pool=mock_pool)

        result = await repo.get_sub_events(event_id="e1", max_depth=3)

        assert len(result) == 2
        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0]
        assert "HAS_SUB_EVENT" in query

    @pytest.mark.asyncio
    async def test_get_sub_events_default_depth(self, mock_pool):
        """Default depth should be reasonable."""
        repo = EventGraphRepo(pool=mock_pool)

        result = await repo.get_sub_events(event_id="e1")

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_sub_events_ladybug_backend(self):
        """get_sub_events must work with LadybugDB backend."""
        pool = MagicMock()
        pool.database_type = "ladybug"
        pool.execute_query = AsyncMock(
            return_value=[
                {"id": "e2", "content": "sub-event 1"},
            ]
        )

        repo = EventGraphRepo(pool=pool)
        result = await repo.get_sub_events(event_id="e1", max_depth=2)

        assert len(result) >= 1


class TestNarrativeHasSourceBiasFrameTone:
    """Tests for Narrative node attributes."""

    def test_narrative_node_attributes(self):
        """NarrativeNode must have source_bias, frame, tone, emphasis attributes."""
        narrative = NarrativeNode(
            id="n1",
            source_bias="left",
            frame="economic_impact",
            tone="critical",
            emphasis="inequality",
        )

        assert narrative.id == "n1"
        assert narrative.source_bias == "left"
        assert narrative.frame == "economic_impact"
        assert narrative.tone == "critical"
        assert narrative.emphasis == "inequality"

    def test_narrative_node_default_emphasis(self):
        """NarrativeNode emphasis should default to empty string."""
        narrative = NarrativeNode(
            id="n2",
            source_bias="center",
            frame="political",
            tone="neutral",
        )

        assert narrative.emphasis == ""

    def test_narrative_node_frozen(self):
        """NarrativeNode should be immutable (frozen dataclass)."""
        narrative = NarrativeNode(id="n1", source_bias="right", frame="security", tone="alarmist")

        with pytest.raises(AttributeError):
            narrative.source_bias = "left"

    @pytest.mark.asyncio
    async def test_get_narratives_for_event(self):
        """get_narratives should return NarrativeNode instances for an event."""
        pool = MagicMock()
        pool.database_type = "neo4j"
        pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "n1",
                    "source_bias": "left",
                    "frame": "economic",
                    "tone": "critical",
                    "emphasis": "inequality",
                },
            ]
        )

        repo = EventGraphRepo(pool=pool)

        result = await repo.get_narratives(event_id="e1")

        assert len(result) == 1
        assert result[0]["source_bias"] == "left"
