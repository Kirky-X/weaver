import pytest

from core.models.shared import CommunityView


class TestCommunityView:
    def test_model_exists(self):
        assert CommunityView is not None

    def test_uses_pydantic_v2_config_dict(self):
        assert CommunityView.model_config.get("from_attributes") is True

    def test_has_all_required_fields(self):
        community = CommunityView(
            id="comm_001",
            name="Tech Community",
        )
        assert community.id == "comm_001"
        assert community.name == "Tech Community"

    def test_default_values(self):
        community = CommunityView(
            id="comm_001",
            name="Test",
        )
        assert community.description is None
        assert community.member_count == 0
        assert community.keywords == []

    def test_model_validate_from_dict(self):
        data = {
            "id": "comm_002",
            "name": "AI Researchers",
            "description": "Community of AI researchers",
            "member_count": 42,
            "keywords": ["AI", "ML", "deep learning"],
        }
        community = CommunityView.model_validate(data)
        assert community.name == "AI Researchers"
        assert community.member_count == 42
        assert community.keywords == ["AI", "ML", "deep learning"]
