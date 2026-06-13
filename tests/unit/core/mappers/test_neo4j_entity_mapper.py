from datetime import datetime

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
            "degree": 5,
            "community_id": "comm_001",
            "confidence": 0.9,
            "last_mentioned": datetime.now(),
        }
        result = Neo4jEntityMapper().to_view(record)
        assert isinstance(result, EntityView)
        assert result.id == "4:abc123"
        assert result.canonical_name == "Test Entity"
        assert result.type == "PERSON"
        assert result.degree == 5
        assert result.community_id == "comm_001"
        assert result.confidence == 0.9

    def test_to_view_uses_validation_alias(self):
        record = {
            "neo4j_id": "4:xyz",
            "name": "Named Via Alias",
            "entity_type": "ORG",
        }
        result = Neo4jEntityMapper().to_view(record)
        assert result.canonical_name == "Named Via Alias"
        assert result.id == "4:xyz"
        assert result.type == "ORG"

    def test_to_view_default_values(self):
        record = {
            "neo4j_id": "4:minimal",
            "name": "Minimal Entity",
            "entity_type": "GPE",
        }
        result = Neo4jEntityMapper().to_view(record)
        assert result.aliases == []
        assert result.description is None
        assert result.degree == 0
        assert result.community_id is None
        assert result.confidence == 1.0
        assert result.last_mentioned is None

    def test_to_view_converts_confidence_string_to_float(self):
        """Mapper SHALL convert string confidence to float."""
        record = {
            "neo4j_id": "4:conv",
            "name": "Conversion Test",
            "entity_type": "ORG",
            "confidence": "0.75",
        }
        result = Neo4jEntityMapper().to_view(record)
        assert result.confidence == 0.75
        assert isinstance(result.confidence, float)

    def test_to_view_handles_missing_community_id(self):
        """Mapper SHALL default community_id to None when missing."""
        record = {
            "neo4j_id": "4:no_comm",
            "name": "No Community",
            "entity_type": "PERSON",
        }
        result = Neo4jEntityMapper().to_view(record)
        assert result.community_id is None

    def test_to_view_ignores_removed_fields(self):
        """Mapper SHALL ignore fields that have been removed from EntityView."""
        record = {
            "neo4j_id": "4:ignore",
            "name": "Ignore Test",
            "entity_type": "ORG",
            "tier": 1,
            "article_count": 10,
        }
        result = Neo4jEntityMapper().to_view(record)
        assert isinstance(result, EntityView)
        assert result.id == "4:ignore"
