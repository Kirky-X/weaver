import pytest

from core.mappers.neo4j_entity_mapper import Neo4jEntityMapper
from core.models.shared import EntityView


class TestNeo4jEntityMapper:
    def test_to_view_returns_entity_view(self):
        record = {
            "neo4j_id": "4:abc123",
            "name": "Test Entity",
            "entity_type": "PERSON",
            "aliases": ["Alias1"],
            "description": "A test entity",
            "tier": 1,
            "article_count": 5,
        }
        result = Neo4jEntityMapper.to_view(record)
        assert isinstance(result, EntityView)
        assert result.neo4j_id == "4:abc123"
        assert result.canonical_name == "Test Entity"
        assert result.entity_type == "PERSON"
        assert result.tier == 1
        assert result.article_count == 5

    def test_to_view_uses_validation_alias(self):
        record = {
            "neo4j_id": "4:xyz",
            "name": "Named Via Alias",
            "entity_type": "ORG",
        }
        result = Neo4jEntityMapper.to_view(record)
        assert result.canonical_name == "Named Via Alias"

    def test_to_view_default_values(self):
        record = {
            "neo4j_id": "4:minimal",
            "name": "Minimal Entity",
            "entity_type": "GPE",
        }
        result = Neo4jEntityMapper.to_view(record)
        assert result.aliases == []
        assert result.description is None
        assert result.tier == 2
        assert result.article_count == 0
