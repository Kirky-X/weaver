"""Tests for EventView.participants and narratives structure (GAP-W03).

Verifies that participants and narratives are list[dict[str, Any]] type,
aligned with EventGraph.get_participants() and get_narratives() return types.
"""

from typing import Any, get_args, get_origin

import pytest
from pydantic import ValidationError

from core.models.shared import EventView


class TestEventViewParticipantsStructure:
    """Verify participants field accepts list[dict] with structured data."""

    def test_participants_accepts_list_of_dicts(self):
        event = EventView(
            id="evt_001",
            summary="Test Event",
            type="conference",
            participants=[
                {"entity_id": "ent_1", "role": "initiator"},
                {"entity_id": "ent_2", "role": "observer"},
            ],
        )
        assert len(event.participants) == 2
        assert event.participants[0]["entity_id"] == "ent_1"
        assert event.participants[0]["role"] == "initiator"

    def test_participants_default_is_empty_list(self):
        event = EventView(id="evt_001", summary="Test Event", type="conference")
        assert event.participants == []

    def test_participants_field_type_is_list_dict(self):
        """Verify the type annotation is list[dict[str, Any]]."""
        field_info = EventView.model_fields["participants"]
        annotation = field_info.annotation
        assert get_origin(annotation) is list
        args = get_args(annotation)
        assert len(args) == 1
        assert get_origin(args[0]) is dict

    def test_participants_from_model_validate(self):
        """Verify participants parsed correctly via model_validate."""
        data = {
            "id": "evt_001",
            "name": "Test",
            "event_type": "conference",
            "participants": [{"entity_id": "e1", "role": "initiator"}],
        }
        event = EventView.model_validate(data)
        assert event.participants[0]["entity_id"] == "e1"


class TestEventViewNarrativesStructure:
    """Verify narratives field accepts list[dict] with structured data."""

    def test_narratives_accepts_list_of_dicts(self):
        event = EventView(
            id="evt_001",
            summary="Test Event",
            type="conference",
            narratives=[
                {
                    "id": "nar_1",
                    "source_bias": "left",
                    "frame": "economic impact",
                    "tone": "critical",
                    "emphasis": "job losses",
                },
                {
                    "id": "nar_2",
                    "source_bias": "right",
                    "frame": "market opportunity",
                    "tone": "optimistic",
                    "emphasis": "innovation",
                },
            ],
        )
        assert len(event.narratives) == 2
        assert event.narratives[0]["source_bias"] == "left"
        assert event.narratives[1]["frame"] == "market opportunity"

    def test_narratives_default_is_empty_list(self):
        event = EventView(id="evt_001", summary="Test Event", type="conference")
        assert event.narratives == []

    def test_narratives_field_type_is_list_dict(self):
        """Verify the type annotation is list[dict[str, Any]]."""
        field_info = EventView.model_fields["narratives"]
        annotation = field_info.annotation
        assert get_origin(annotation) is list
        args = get_args(annotation)
        assert len(args) == 1
        assert get_origin(args[0]) is dict

    def test_narratives_with_confidence_field(self):
        """Verify narratives accept confidence field per design doc."""
        event = EventView(
            id="evt_001",
            summary="Test Event",
            type="conference",
            narratives=[
                {"text": "Event description", "source": "article_123", "confidence": 0.8},
            ],
        )
        assert event.narratives[0]["confidence"] == 0.8


class TestEventViewBackwardCompatibility:
    """Verify that list[str] values are no longer accepted for participants/narratives."""

    def test_participants_rejects_list_of_strings(self):
        """After GAP-W03 fix, participants should not accept list[str]."""
        with pytest.raises(ValidationError):
            EventView(
                id="evt_001",
                summary="Test Event",
                type="conference",
                participants=["Entity A", "Entity B"],
            )

    def test_narratives_rejects_list_of_strings(self):
        """After GAP-W03 fix, narratives should not accept list[str]."""
        with pytest.raises(ValidationError):
            EventView(
                id="evt_001",
                summary="Test Event",
                type="conference",
                narratives=["Narrative 1", "Narrative 2"],
            )
