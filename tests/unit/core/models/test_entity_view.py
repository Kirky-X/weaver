from datetime import datetime

import pytest

from core.models.shared import EntityView

# Fields defined in ADD §1.5.1 that SHALL be present
REQUIRED_FIELDS = {"id", "type", "degree", "community_id", "confidence", "last_mentioned"}

# Fields that SHALL be removed per spec
REMOVED_FIELDS = {"neo4j_id", "entity_type", "tier", "article_count"}


class TestEntityViewAlignment:
    """Tests for EntityView field alignment with ADD §1.5.1."""

    def test_id_field_exists(self):
        entity = EntityView(id="4:abc123", canonical_name="Test Entity", type="PERSON")
        assert entity.id == "4:abc123"

    def test_type_field_exists(self):
        entity = EntityView(id="4:abc123", canonical_name="Test Entity", type="PERSON")
        assert entity.type == "PERSON"

    def test_degree_field_exists(self):
        entity = EntityView(id="4:abc123", canonical_name="Test Entity", type="PERSON")
        assert hasattr(entity, "degree")
        assert entity.degree == 0

    def test_community_id_field_exists(self):
        entity = EntityView(id="4:abc123", canonical_name="Test Entity", type="PERSON")
        assert hasattr(entity, "community_id")
        assert entity.community_id is None

    def test_confidence_field_exists(self):
        entity = EntityView(id="4:abc123", canonical_name="Test Entity", type="PERSON")
        assert hasattr(entity, "confidence")
        assert entity.confidence == 1.0

    def test_last_mentioned_field_exists(self):
        entity = EntityView(id="4:abc123", canonical_name="Test Entity", type="PERSON")
        assert hasattr(entity, "last_mentioned")
        assert entity.last_mentioned is None

    def test_last_mentioned_can_be_set(self):
        now = datetime.now()
        entity = EntityView(
            id="4:abc123", canonical_name="Test Entity", type="PERSON", last_mentioned=now
        )
        assert entity.last_mentioned == now

    def test_removed_fields_not_present(self):
        field_names = set(EntityView.model_fields.keys())
        for field in REMOVED_FIELDS:
            assert field not in field_names, f"Removed field '{field}' still present in EntityView"

    def test_required_fields_present(self):
        field_names = set(EntityView.model_fields.keys())
        for field in REQUIRED_FIELDS:
            assert field in field_names, f"Required field '{field}' missing from EntityView"

    def test_uses_pydantic_v2_config_dict(self):
        assert EntityView.model_config.get("from_attributes") is True
        assert EntityView.model_config.get("populate_by_name") is True

    def test_validation_alias_neo4j_id_maps_to_id(self):
        data = {"neo4j_id": "4:xyz789", "name": "Acme Corp", "entity_type": "ORG"}
        entity = EntityView.model_validate(data)
        assert entity.id == "4:xyz789"

    def test_validation_alias_entity_type_maps_to_type(self):
        data = {"id": "4:xyz789", "name": "Acme Corp", "entity_type": "ORG"}
        entity = EntityView.model_validate(data)
        assert entity.type == "ORG"

    def test_canonical_name_via_validation_alias(self):
        data = {"id": "4:abc", "name": "Aliased Name", "type": "PERSON"}
        entity = EntityView.model_validate(data)
        assert entity.canonical_name == "Aliased Name"

    def test_default_values(self):
        entity = EntityView(id="4:abc123", canonical_name="Test Entity", type="PERSON")
        assert entity.aliases == []
        assert entity.description is None
        assert entity.degree == 0
        assert entity.community_id is None
        assert entity.confidence == 1.0
        assert entity.last_mentioned is None

    def test_all_new_fields_set(self):
        now = datetime.now()
        entity = EntityView(
            id="4:full",
            canonical_name="Full Entity",
            type="ORG",
            degree=5,
            community_id="comm_001",
            confidence=0.85,
            last_mentioned=now,
        )
        assert entity.degree == 5
        assert entity.community_id == "comm_001"
        assert entity.confidence == 0.85
        assert entity.last_mentioned == now

    def test_serialize_to_dict(self):
        entity = EntityView(id="4:abc", canonical_name="Test", type="GPE")
        data = entity.model_dump()
        assert isinstance(data, dict)
        assert data["id"] == "4:abc"
        assert data["type"] == "GPE"
        assert data["canonical_name"] == "Test"
        assert data["degree"] == 0
        assert data["confidence"] == 1.0

    def test_removed_fields_not_in_dump(self):
        entity = EntityView(id="4:abc", canonical_name="Test", type="GPE")
        data = entity.model_dump()
        for field in REMOVED_FIELDS:
            assert field not in data, f"Removed field '{field}' still in model_dump()"
