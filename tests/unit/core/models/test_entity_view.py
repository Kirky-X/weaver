import pytest

from core.models.shared import EntityView


class TestEntityView:
    def test_model_exists(self):
        assert EntityView is not None

    def test_uses_pydantic_v2_config_dict(self):
        assert EntityView.model_config.get("from_attributes") is True
        assert EntityView.model_config.get("populate_by_name") is True

    def test_has_all_required_fields(self):
        entity = EntityView(
            neo4j_id="4:abc123",
            name="Test Entity",
            entity_type="PERSON",
        )
        assert entity.neo4j_id == "4:abc123"
        assert entity.canonical_name == "Test Entity"
        assert entity.entity_type == "PERSON"

    def test_default_values(self):
        entity = EntityView(
            neo4j_id="4:abc123",
            name="Test Entity",
            entity_type="ORG",
        )
        assert entity.aliases == []
        assert entity.description is None
        assert entity.tier == 2
        assert entity.article_count == 0

    def test_model_validate_from_dict(self):
        data = {
            "neo4j_id": "4:xyz789",
            "name": "Acme Corp",
            "entity_type": "ORG",
            "aliases": ["Acme", "ACME"],
            "description": "A test entity",
            "tier": 1,
            "article_count": 10,
        }
        entity = EntityView.model_validate(data)
        assert entity.canonical_name == "Acme Corp"
        assert entity.tier == 1
        assert entity.article_count == 10
        assert entity.aliases == ["Acme", "ACME"]

    def test_validation_alias_name(self):
        data = {
            "neo4j_id": "4:abc",
            "name": "Aliased Name",
            "entity_type": "PERSON",
        }
        entity = EntityView.model_validate(data)
        assert entity.canonical_name == "Aliased Name"

    def test_model_validate_from_orm_instance(self):
        class FakeORMRow:
            neo4j_id = "4:test123"
            name = "Test Person"
            entity_type = "PERSON"
            aliases = ["Person"]
            description = "A person"
            tier = 2
            article_count = 5

        entity = EntityView.model_validate(FakeORMRow())
        assert entity.neo4j_id == "4:test123"
        assert entity.canonical_name == "Test Person"
        assert entity.entity_type == "PERSON"
        assert entity.article_count == 5

    def test_serialize_to_dict(self):
        entity = EntityView(
            neo4j_id="4:abc",
            name="Test",
            entity_type="GPE",
        )
        data = entity.model_dump()
        assert isinstance(data, dict)
        assert data["canonical_name"] == "Test"
        assert data["entity_type"] == "GPE"
