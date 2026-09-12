# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Mapper missing-field tolerance tests (surviving live mappers only)."""

from core.mappers.neo4j_entity_mapper import Neo4jEntityMapper
from core.models.shared import EntityView


class TestMapperMissingFields:
    def test_neo4j_mapper_minimal_fields(self):
        result = Neo4jEntityMapper().to_view(
            {
                "neo4j_id": "4:minimal",
                "name": "Minimal",
                "entity_type": "PERSON",
            }
        )
        assert isinstance(result, EntityView)
        assert result.aliases == []
        assert result.description is None
        assert result.degree == 0
        assert result.community_id is None
        assert result.confidence == 1.0
        assert result.last_mentioned is None
