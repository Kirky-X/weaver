import pytest

from core.models.shared import CommunityView
from tests.unit.core.models._base import ViewModelTestBase

# Fields defined in ADD §1.5.1 that SHALL be present
REQUIRED_FIELDS = {
    "title",
    "summary",
    "level",
    "rank",
    "entity_count",
    "article_count",
    "embedding",
}

# Fields that SHALL be removed per spec
REMOVED_FIELDS = {"name", "description", "member_count"}


class TestCommunityViewAlignment(ViewModelTestBase):
    """Tests for CommunityView field alignment with ADD §1.5.1."""

    model_class = CommunityView
    required_fields = REQUIRED_FIELDS
    removed_fields = REMOVED_FIELDS

    def _create_minimal_instance(self):
        return CommunityView(id="comm_001", title="Test")

    def test_title_field_exists(self):
        community = CommunityView(id="comm_001", title="Tech Community")
        assert community.title == "Tech Community"

    def test_summary_field_exists(self):
        community = CommunityView(id="comm_001", title="Test", summary="A test community")
        assert community.summary == "A test community"

    def test_level_field_exists(self):
        community = self._create_minimal_instance()
        assert hasattr(community, "level")
        assert community.level == 0

    def test_rank_field_exists(self):
        community = self._create_minimal_instance()
        assert hasattr(community, "rank")
        assert community.rank == 0.0

    def test_entity_count_field_exists(self):
        community = self._create_minimal_instance()
        assert hasattr(community, "entity_count")
        assert community.entity_count == 0

    def test_article_count_field_exists(self):
        community = self._create_minimal_instance()
        assert hasattr(community, "article_count")
        assert community.article_count == 0

    def test_embedding_field_exists(self):
        community = self._create_minimal_instance()
        assert hasattr(community, "embedding")
        assert community.embedding is None

    def test_embedding_can_be_set(self):
        community = CommunityView(id="comm_001", title="Test", embedding=[0.1, 0.2, 0.3])
        assert community.embedding == [0.1, 0.2, 0.3]

    def test_uses_pydantic_v2_config_dict(self):
        assert CommunityView.model_config.get("from_attributes") is True
        assert CommunityView.model_config.get("populate_by_name") is True

    def test_validation_alias_name_maps_to_title(self):
        data = {"id": "comm_002", "name": "AI Researchers"}
        community = CommunityView.model_validate(data)
        assert community.title == "AI Researchers"

    def test_validation_alias_description_maps_to_summary(self):
        data = {"id": "comm_002", "title": "Test", "description": "A community"}
        community = CommunityView.model_validate(data)
        assert community.summary == "A community"

    def test_default_values(self):
        community = self._create_minimal_instance()
        assert community.summary is None
        assert community.keywords == []
        assert community.level == 0
        assert community.rank == 0.0
        assert community.entity_count == 0
        assert community.article_count == 0
        assert community.embedding is None

    def test_all_new_fields_set(self):
        community = CommunityView(
            id="comm_full",
            title="Full Community",
            summary="A full community",
            level=3,
            rank=0.95,
            entity_count=42,
            article_count=100,
            embedding=[0.1, 0.2, 0.3],
        )
        assert community.level == 3
        assert community.rank == 0.95
        assert community.entity_count == 42
        assert community.article_count == 100
        assert community.embedding == [0.1, 0.2, 0.3]

    def test_serialize_to_dict(self):
        """Override to add specific field assertions."""
        community = self._create_minimal_instance()
        data = community.model_dump()
        assert isinstance(data, dict)
        assert data["title"] == "Test"
        assert data["level"] == 0
        assert data["rank"] == 0.0
