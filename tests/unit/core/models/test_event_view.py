from datetime import datetime

import pytest

from core.models.shared import EventView


class TestEventView:
    def test_model_exists(self):
        assert EventView is not None

    def test_uses_pydantic_v2_config_dict(self):
        assert EventView.model_config.get("from_attributes") is True

    def test_has_all_required_fields(self):
        event = EventView(
            id="evt_001",
            name="Test Event",
            event_type="conference",
        )
        assert event.id == "evt_001"
        assert event.name == "Test Event"
        assert event.event_type == "conference"

    def test_default_values(self):
        event = EventView(
            id="evt_001",
            name="Test Event",
            event_type="meeting",
        )
        assert event.description is None
        assert event.start_time is None
        assert event.end_time is None
        assert event.location is None
        assert event.article_count == 0

    def test_model_validate_from_dict(self):
        now = datetime.now()
        data = {
            "id": "evt_002",
            "name": "Summit 2026",
            "event_type": "summit",
            "description": "Annual summit",
            "start_time": now,
            "end_time": now,
            "location": "New York",
            "article_count": 15,
        }
        event = EventView.model_validate(data)
        assert event.name == "Summit 2026"
        assert event.location == "New York"
        assert event.article_count == 15
        assert event.start_time == now
