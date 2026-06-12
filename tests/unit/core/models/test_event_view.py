from datetime import datetime
from uuid import uuid4

import pytest

from core.models.shared import EventView
from tests.unit.core.models._base import ViewModelTestBase

# Fields defined in ADD §1.5.1 that SHALL be present
REQUIRED_FIELDS = {
    "type",
    "summary",
    "time",
    "status",
    "importance",
    "participants",
    "narratives",
    "source_article_id",
}

# Fields that SHALL be removed per spec
REMOVED_FIELDS = {"event_type", "name", "start_time", "end_time", "article_count"}


class TestEventViewAlignment(ViewModelTestBase):
    """Tests for EventView field alignment with ADD §1.5.1."""

    model_class = EventView
    required_fields = REQUIRED_FIELDS
    removed_fields = REMOVED_FIELDS

    def _create_minimal_instance(self):
        return EventView(id="evt_001", summary="Test Event", type="conference")

    def test_type_field_exists(self):
        event = self._create_minimal_instance()
        assert event.type == "conference"

    def test_summary_field_exists(self):
        event = self._create_minimal_instance()
        assert event.summary == "Test Event"

    def test_time_field_exists(self):
        now = datetime.now()
        event = EventView(id="evt_001", summary="Test Event", type="conference", time=now)
        assert event.time == now

    def test_status_field_exists(self):
        event = self._create_minimal_instance()
        assert hasattr(event, "status")
        assert event.status == "confirmed"

    def test_importance_field_exists(self):
        event = self._create_minimal_instance()
        assert hasattr(event, "importance")
        assert event.importance == 0.5

    def test_participants_field_exists(self):
        event = self._create_minimal_instance()
        assert hasattr(event, "participants")
        assert event.participants == []

    def test_narratives_field_exists(self):
        event = self._create_minimal_instance()
        assert hasattr(event, "narratives")
        assert event.narratives == []

    def test_source_article_id_field_exists(self):
        event = self._create_minimal_instance()
        assert hasattr(event, "source_article_id")
        assert event.source_article_id is None

    def test_source_article_id_can_be_set(self):
        aid = str(uuid4())
        event = EventView(
            id="evt_001", summary="Test Event", type="conference", source_article_id=aid
        )
        assert event.source_article_id == aid

    def test_uses_pydantic_v2_config_dict(self):
        assert EventView.model_config.get("from_attributes") is True
        assert EventView.model_config.get("populate_by_name") is True

    def test_validation_alias_event_type_maps_to_type(self):
        data = {"id": "evt_002", "name": "Summit", "event_type": "summit"}
        event = EventView.model_validate(data)
        assert event.type == "summit"

    def test_validation_alias_name_maps_to_summary(self):
        data = {"id": "evt_002", "name": "Summit 2026", "type": "summit"}
        event = EventView.model_validate(data)
        assert event.summary == "Summit 2026"

    def test_validation_alias_start_time_maps_to_time(self):
        now = datetime.now()
        data = {"id": "evt_003", "summary": "Event", "type": "meeting", "start_time": now}
        event = EventView.model_validate(data)
        assert event.time == now

    def test_default_values(self):
        event = EventView(id="evt_001", summary="Test Event", type="meeting")
        assert event.description is None
        assert event.time is None
        assert event.location is None
        assert event.status == "confirmed"
        assert event.importance == 0.5
        assert event.participants == []
        assert event.narratives == []
        assert event.source_article_id is None

    def test_all_new_fields_set(self):
        now = datetime.now()
        event = EventView(
            id="evt_full",
            summary="Full Event",
            type="conference",
            time=now,
            status="ongoing",
            importance=0.9,
            participants=[
                {"entity_id": "Alice", "role": "initiator"},
                {"entity_id": "Bob", "role": "observer"},
            ],
            narratives=[{"text": "narrative1", "source": "article_1", "confidence": 0.9}],
            source_article_id=str(uuid4()),
        )
        assert event.status == "ongoing"
        assert event.importance == 0.9
        assert len(event.participants) == 2
        assert event.participants[0]["entity_id"] == "Alice"
        assert len(event.narratives) == 1
        assert event.narratives[0]["text"] == "narrative1"
        assert event.time == now

    def test_serialize_to_dict(self):
        """Override to add specific field assertions."""
        event = EventView(id="evt_001", summary="Test", type="meeting")
        data = event.model_dump()
        assert isinstance(data, dict)
        assert data["type"] == "meeting"
        assert data["summary"] == "Test"
        assert data["status"] == "confirmed"
        assert data["importance"] == 0.5
