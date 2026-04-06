# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for GraphQueryBuilder pattern."""

import pytest

from core.db.graph_query import (
    CommunitySearchConfig,
    EntitySearchConfig,
    GraphDatabaseType,
    GraphQueryBuilder,
    LadybugQueryBuilder,
    Neo4jQueryBuilder,
    RelatedEntitiesConfig,
    create_graph_query_builder,
)
from core.db.safe_query import InvalidIdentifierError


class TestGraphDatabaseTypeEnum:
    """Tests for GraphDatabaseType enum."""

    def test_neo4j_value(self) -> None:
        assert GraphDatabaseType.NEO4J.value == "neo4j"

    def test_ladybug_value(self) -> None:
        assert GraphDatabaseType.LADYBUG.value == "ladybug"

    def test_from_string(self) -> None:
        assert GraphDatabaseType("neo4j") == GraphDatabaseType.NEO4J
        assert GraphDatabaseType("ladybug") == GraphDatabaseType.LADYBUG

    def test_enum_members_count(self) -> None:
        assert len(list(GraphDatabaseType)) == 2


class TestEntitySearchConfig:
    """Tests for EntitySearchConfig dataclass."""

    def test_default_values(self) -> None:
        config = EntitySearchConfig()
        assert config.query == ""
        assert config.limit == 20
        assert config.use_aliases is True

    def test_custom_values(self) -> None:
        config = EntitySearchConfig(
            query="test entity",
            limit=50,
            use_aliases=False,
        )
        assert config.query == "test entity"
        assert config.limit == 50
        assert config.use_aliases is False

    def test_frozen(self) -> None:
        config = EntitySearchConfig()
        with pytest.raises(AttributeError):
            config.query = "new query"  # type: ignore[misc]

    def test_frozen_limit(self) -> None:
        config = EntitySearchConfig()
        with pytest.raises(AttributeError):
            config.limit = 100  # type: ignore[misc]


class TestRelatedEntitiesConfig:
    """Tests for RelatedEntitiesConfig dataclass."""

    def test_default_values(self) -> None:
        config = RelatedEntitiesConfig()
        assert config.entity_names == ()
        assert config.relation_types == ()
        assert config.max_hops == 2
        assert config.limit == 20

    def test_custom_values(self) -> None:
        config = RelatedEntitiesConfig(
            entity_names=("entity1", "entity2"),
            relation_types=("RELATED_TO", "MENTIONS"),
            max_hops=3,
            limit=50,
        )
        assert config.entity_names == ("entity1", "entity2")
        assert config.relation_types == ("RELATED_TO", "MENTIONS")
        assert config.max_hops == 3
        assert config.limit == 50

    def test_frozen(self) -> None:
        config = RelatedEntitiesConfig()
        with pytest.raises(AttributeError):
            config.max_hops = 5  # type: ignore[misc]

    def test_empty_entity_names(self) -> None:
        config = RelatedEntitiesConfig(entity_names=())
        assert config.entity_names == ()

    def test_single_entity_name(self) -> None:
        config = RelatedEntitiesConfig(entity_names=("only_one",))
        assert config.entity_names == ("only_one",)


class TestCommunitySearchConfig:
    """Tests for CommunitySearchConfig dataclass."""

    def test_default_values(self) -> None:
        config = CommunitySearchConfig()
        assert config.level == 0
        assert config.query == ""
        assert config.limit == 10

    def test_custom_values(self) -> None:
        config = CommunitySearchConfig(
            level=2,
            query="test community",
            limit=25,
        )
        assert config.level == 2
        assert config.query == "test community"
        assert config.limit == 25

    def test_frozen(self) -> None:
        config = CommunitySearchConfig()
        with pytest.raises(AttributeError):
            config.level = 3  # type: ignore[misc]

    def test_empty_query(self) -> None:
        config = CommunitySearchConfig(query="")
        assert config.query == ""


class TestNeo4jQueryBuilder:
    """Tests for Neo4j Cypher query builder."""

    @pytest.fixture
    def builder(self) -> Neo4jQueryBuilder:
        return Neo4jQueryBuilder()

    def test_database_type(self, builder: Neo4jQueryBuilder) -> None:
        assert builder.database_type == GraphDatabaseType.NEO4J

    def test_build_entity_search_query_with_aliases(self, builder: Neo4jQueryBuilder) -> None:
        config = EntitySearchConfig(query="test", limit=10, use_aliases=True)
        result = builder.build_entity_search_query(config)
        assert "MATCH (e:Entity)" in result
        assert "toLower(e.canonical_name) CONTAINS $query" in result
        assert "any(alias IN e.aliases" in result
        assert "LIMIT $limit" in result

    def test_build_entity_search_query_without_aliases(self, builder: Neo4jQueryBuilder) -> None:
        config = EntitySearchConfig(query="test", limit=10, use_aliases=False)
        result = builder.build_entity_search_query(config)
        assert "MATCH (e:Entity)" in result
        assert "toLower(e.canonical_name) CONTAINS $query" in result
        assert "aliases" not in result
        assert "LIMIT $limit" in result

    def test_build_entities_by_names_query(self, builder: Neo4jQueryBuilder) -> None:
        result = builder.build_entities_by_names_query(["entity1", "entity2"], 10)
        assert "MATCH (e:Entity)" in result
        assert "e.canonical_name IN $names" in result
        assert "RETURN e.canonical_name" in result
        assert "e.type AS type" in result
        assert "e.description AS description" in result
        assert "e.aliases AS aliases" in result
        assert "LIMIT $limit" in result

    def test_build_related_entities_query_with_types(self, builder: Neo4jQueryBuilder) -> None:
        config = RelatedEntitiesConfig(
            entity_names=("e1", "e2"),
            relation_types=("MENTIONS", "RELATED_TO"),
            max_hops=2,
            limit=10,
        )
        result = builder.build_related_entities_query(config)
        assert "MATCH (e:Entity)" in result
        assert "-[:MENTIONS|RELATED_TO*1..2]-" in result
        assert "e.canonical_name IN $names" in result
        assert "ORDER BY connection_count DESC" in result

    def test_build_related_entities_query_without_types(self, builder: Neo4jQueryBuilder) -> None:
        config = RelatedEntitiesConfig(
            entity_names=("e1", "e2"),
            relation_types=(),
            max_hops=3,
            limit=10,
        )
        result = builder.build_related_entities_query(config)
        assert "MATCH (e:Entity)" in result
        assert "-[:RELATED_TO*1..3]-" in result
        assert "e.canonical_name IN $names" in result

    def test_build_related_entities_query_custom_max_hops(self, builder: Neo4jQueryBuilder) -> None:
        config = RelatedEntitiesConfig(
            entity_names=("e1",),
            max_hops=5,
            limit=20,
        )
        result = builder.build_related_entities_query(config)
        assert "*1..5" in result

    def test_build_relationships_query_with_types(self, builder: Neo4jQueryBuilder) -> None:
        result = builder.build_relationships_query(
            ["e1", "e2"],
            ["MENTIONS", "RELATED_TO"],
            10,
        )
        assert "UNION ALL" in result
        assert "MATCH (e1:Entity)-[r:MENTIONS]->" in result
        assert "MATCH (e1:Entity)-[r:RELATED_TO]->" in result

    def test_build_relationships_query_without_types(self, builder: Neo4jQueryBuilder) -> None:
        result = builder.build_relationships_query(
            ["e1", "e2"],
            None,
            10,
        )
        assert "MATCH (e1:Entity)-[r:RELATED_TO]->" in result
        assert "UNION" not in result
        assert "ORDER BY coalesce(r.weight" in result

    def test_build_relationships_query_single_type(self, builder: Neo4jQueryBuilder) -> None:
        result = builder.build_relationships_query(
            ["e1"],
            ["MENTIONS"],
            5,
        )
        assert "MATCH (e1:Entity)-[r:MENTIONS]->" in result
        assert "UNION" not in result

    def test_build_articles_by_entities_query(self, builder: Neo4jQueryBuilder) -> None:
        result = builder.build_articles_by_entities_query(["e1", "e2"], 10)
        assert "MATCH (a:Article)-[:MENTIONS]->(e:Entity)" in result
        assert "e.canonical_name IN $names" in result
        assert "RETURN DISTINCT a.pg_id AS id" in result
        assert "ORDER BY a.publish_time DESC" in result

    def test_build_community_search_query_with_text(self, builder: Neo4jQueryBuilder) -> None:
        config = CommunitySearchConfig(level=1, query="test", limit=10)
        result = builder.build_community_search_query(config)
        assert "MATCH (c:Community)" in result
        assert "c.level = $level" in result
        assert "toLower(c.title) CONTAINS $query" in result
        assert "toLower(c.summary) CONTAINS $query" in result
        assert "ORDER BY c.rank DESC" in result

    def test_build_community_search_query_without_text(self, builder: Neo4jQueryBuilder) -> None:
        config = CommunitySearchConfig(level=2, query="", limit=15)
        result = builder.build_community_search_query(config)
        assert "MATCH (c:Community)" in result
        assert "c.level = $level" in result
        assert "CONTAINS" not in result
        assert "ORDER BY c.rank DESC" in result

    def test_build_community_entities_query(self, builder: Neo4jQueryBuilder) -> None:
        result = builder.build_community_entities_query("550e8400-e29b-41d4-a716-446655440000", 10)
        assert "MATCH (c:Community {id: $community_id})" in result
        assert "-[:HAS_ENTITY]->(e:Entity)" in result
        assert "RETURN e.canonical_name" in result

    def test_build_key_entities_query(self, builder: Neo4jQueryBuilder) -> None:
        result = builder.build_key_entities_query(
            ["550e8400-e29b-41d4-a716-446655440000", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"], 20
        )
        assert "MATCH (c:Community)-[:HAS_ENTITY]->(e:Entity)" in result
        assert "c.id IN $community_ids" in result
        assert "ORDER BY community_count DESC, degree DESC" in result

    def test_build_communities_exist_query_with_level(self, builder: Neo4jQueryBuilder) -> None:
        result = builder.build_communities_exist_query(1)
        assert "MATCH (c:Community)" in result
        assert "c.level = $level" in result
        assert "RETURN count(c) AS count" in result

    def test_build_communities_exist_query_without_level(self, builder: Neo4jQueryBuilder) -> None:
        result = builder.build_communities_exist_query(None)
        assert "MATCH (c:Community)" in result
        assert "level" not in result
        assert "RETURN count(c) AS count" in result


class TestLadybugQueryBuilder:
    """Tests for LadybugDB SQL-like query builder."""

    @pytest.fixture
    def builder(self) -> LadybugQueryBuilder:
        return LadybugQueryBuilder()

    def test_database_type(self, builder: LadybugQueryBuilder) -> None:
        assert builder.database_type == GraphDatabaseType.LADYBUG

    def test_build_entity_search_query_with_aliases(self, builder: LadybugQueryBuilder) -> None:
        config = EntitySearchConfig(query="test", limit=10, use_aliases=True)
        result = builder.build_entity_search_query(config)
        assert "MATCH (e:Entity)" in result
        assert "LOWER(e.canonical_name) CONTAINS $query" in result
        # Note: LadybugDB doesn't support alias array functions same way
        assert "LIMIT $limit" in result

    def test_build_entity_search_query_without_aliases(self, builder: LadybugQueryBuilder) -> None:
        config = EntitySearchConfig(query="test", limit=10, use_aliases=False)
        result = builder.build_entity_search_query(config)
        assert "MATCH (e:Entity)" in result
        assert "LOWER(e.canonical_name) CONTAINS $query" in result

    def test_build_entities_by_names_query(self, builder: LadybugQueryBuilder) -> None:
        result = builder.build_entities_by_names_query(["entity1", "entity2"], 10)
        assert "MATCH (e:Entity)" in result
        # LadybugDB now uses parameterized queries
        assert "$names" in result
        assert "$limit" in result

    def test_build_entities_by_names_query_empty_list(self, builder: LadybugQueryBuilder) -> None:
        result = builder.build_entities_by_names_query([], 10)
        assert "MATCH (e:Entity)" in result
        assert "$names" in result

    def test_build_related_entities_query_with_types(self, builder: LadybugQueryBuilder) -> None:
        config = RelatedEntitiesConfig(
            entity_names=("e1", "e2"),
            relation_types=("MENTIONS", "RELATED_TO"),
            max_hops=2,
            limit=10,
        )
        result = builder.build_related_entities_query(config)
        assert "MATCH (e:Entity)" in result
        assert "*1..2" in result
        assert "r.edge_type IN $relation_types" in result

    def test_build_related_entities_query_without_types(self, builder: LadybugQueryBuilder) -> None:
        config = RelatedEntitiesConfig(
            entity_names=("e1",),
            max_hops=3,
            limit=20,
        )
        result = builder.build_related_entities_query(config)
        assert "MATCH (e:Entity)" in result
        assert "*1..3" in result
        assert "edge_type" not in result

    def test_build_relationships_query_with_types(self, builder: LadybugQueryBuilder) -> None:
        result = builder.build_relationships_query(
            ["e1", "e2"],
            ["MENTIONS", "RELATED_TO"],
            10,
        )
        assert "MATCH (e1:Entity)-[r:RELATED_TO]->" in result
        assert "r.edge_type IN $relation_types" in result
        assert "$names" in result

    def test_build_relationships_query_without_types(self, builder: LadybugQueryBuilder) -> None:
        result = builder.build_relationships_query(
            ["e1", "e2"],
            None,
            10,
        )
        assert "MATCH (e1:Entity)-[r:RELATED_TO]->" in result
        assert "edge_type" not in result or "AS relation_type" in result

    def test_build_articles_by_entities_query(self, builder: LadybugQueryBuilder) -> None:
        result = builder.build_articles_by_entities_query(["e1", "e2"], 10)
        assert "MATCH (a:Article)-[:MENTIONS]->(e:Entity)" in result
        assert "$names" in result
        assert "$limit" in result

    def test_build_community_search_query_with_text(self, builder: LadybugQueryBuilder) -> None:
        config = CommunitySearchConfig(level=1, query="test", limit=10)
        result = builder.build_community_search_query(config)
        assert "MATCH (c:Community)" in result
        assert "c.level = $level" in result
        assert "LOWER(c.title) CONTAINS $query" in result
        assert "$limit" in result

    def test_build_community_search_query_without_text(self, builder: LadybugQueryBuilder) -> None:
        config = CommunitySearchConfig(level=2, query="", limit=15)
        result = builder.build_community_search_query(config)
        assert "MATCH (c:Community)" in result
        assert "c.level = $level" in result
        assert "CONTAINS" not in result
        assert "$limit" in result

    def test_build_community_entities_query(self, builder: LadybugQueryBuilder) -> None:
        result = builder.build_community_entities_query("550e8400-e29b-41d4-a716-446655440000", 10)
        assert "MATCH (c:Community {id: $community_id})" in result
        assert "-[:HAS_ENTITY]->(e:Entity)" in result
        assert "$limit" in result

    def test_build_key_entities_query(self, builder: LadybugQueryBuilder) -> None:
        result = builder.build_key_entities_query(
            ["550e8400-e29b-41d4-a716-446655440000", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"], 20
        )
        assert "MATCH (c:Community)-[:HAS_ENTITY]->(e:Entity)" in result
        assert "c.id IN $community_ids" in result
        assert "ORDER BY community_count DESC" in result
        # Note: LadybugDB version doesn't include degree calculation
        assert "degree" not in result

    def test_build_communities_exist_query_with_level(self, builder: LadybugQueryBuilder) -> None:
        result = builder.build_communities_exist_query(1)
        assert "MATCH (c:Community)" in result
        assert "c.level = $level" in result
        assert "RETURN count(c) AS count" in result

    def test_build_communities_exist_query_without_level(
        self, builder: LadybugQueryBuilder
    ) -> None:
        result = builder.build_communities_exist_query(None)
        assert "MATCH (c:Community)" in result
        assert "level" not in result
        assert "RETURN count(c) AS count" in result


class TestCreateGraphQueryBuilder:
    """Tests for factory function."""

    def test_create_neo4j_builder_from_enum(self) -> None:
        builder = create_graph_query_builder(GraphDatabaseType.NEO4J)
        assert isinstance(builder, Neo4jQueryBuilder)

    def test_create_ladybug_builder_from_enum(self) -> None:
        builder = create_graph_query_builder(GraphDatabaseType.LADYBUG)
        assert isinstance(builder, LadybugQueryBuilder)

    def test_create_neo4j_builder_from_string(self) -> None:
        builder = create_graph_query_builder("neo4j")
        assert isinstance(builder, Neo4jQueryBuilder)

    def test_create_ladybug_builder_from_string(self) -> None:
        builder = create_graph_query_builder("ladybug")
        assert isinstance(builder, LadybugQueryBuilder)

    def test_create_builder_case_insensitive(self) -> None:
        builder = create_graph_query_builder("NEO4J")
        assert isinstance(builder, Neo4jQueryBuilder)

        builder2 = create_graph_query_builder("LADYBUG")
        assert isinstance(builder2, LadybugQueryBuilder)

    def test_create_builder_mixed_case(self) -> None:
        builder = create_graph_query_builder("Neo4j")
        assert isinstance(builder, Neo4jQueryBuilder)

    def test_create_builder_invalid_type(self) -> None:
        with pytest.raises(ValueError, match="Unsupported graph database type"):
            create_graph_query_builder("invalid")

    def test_create_builder_invalid_type_lists_supported(self) -> None:
        with pytest.raises(ValueError, match="neo4j"):
            create_graph_query_builder("unknown")
        with pytest.raises(ValueError, match="ladybug"):
            create_graph_query_builder("unknown")


class TestGraphQueryBuilderProtocol:
    """Tests for GraphQueryBuilder protocol compliance."""

    def test_neo4j_builder_implements_protocol(self) -> None:
        builder = Neo4jQueryBuilder()
        # Verify all required methods exist
        assert hasattr(builder, "database_type")
        assert hasattr(builder, "build_entity_search_query")
        assert hasattr(builder, "build_entities_by_names_query")
        assert hasattr(builder, "build_related_entities_query")
        assert hasattr(builder, "build_relationships_query")
        assert hasattr(builder, "build_articles_by_entities_query")
        assert hasattr(builder, "build_community_search_query")
        assert hasattr(builder, "build_community_entities_query")
        assert hasattr(builder, "build_key_entities_query")
        assert hasattr(builder, "build_communities_exist_query")

    def test_ladybug_builder_implements_protocol(self) -> None:
        builder = LadybugQueryBuilder()
        assert hasattr(builder, "database_type")
        assert hasattr(builder, "build_entity_search_query")
        assert hasattr(builder, "build_entities_by_names_query")
        assert hasattr(builder, "build_related_entities_query")
        assert hasattr(builder, "build_relationships_query")
        assert hasattr(builder, "build_articles_by_entities_query")
        assert hasattr(builder, "build_community_search_query")
        assert hasattr(builder, "build_community_entities_query")
        assert hasattr(builder, "build_key_entities_query")
        assert hasattr(builder, "build_communities_exist_query")

    def test_both_builders_return_string(self) -> None:
        neo4j = Neo4jQueryBuilder()
        ladybug = LadybugQueryBuilder()

        config = EntitySearchConfig(query="test", limit=10)

        neo4j_result = neo4j.build_entity_search_query(config)
        ladybug_result = ladybug.build_entity_search_query(config)

        assert isinstance(neo4j_result, str)
        assert isinstance(ladybug_result, str)


class TestQueryOutputComparison:
    """Tests comparing query outputs between Neo4j and Ladybug builders."""

    def test_entity_search_syntax_differs(self) -> None:
        neo4j = Neo4jQueryBuilder()
        ladybug = LadybugQueryBuilder()

        config = EntitySearchConfig(query="test", limit=10, use_aliases=True)

        neo4j_result = neo4j.build_entity_search_query(config)
        ladybug_result = ladybug.build_entity_search_query(config)

        # Neo4j uses toLower, Ladybug uses LOWER
        assert "toLower" in neo4j_result
        assert "LOWER" in ladybug_result

    def test_entities_by_names_parameter_style_differs(self) -> None:
        neo4j = Neo4jQueryBuilder()
        ladybug = LadybugQueryBuilder()

        names = ["entity1", "entity2"]

        neo4j_result = neo4j.build_entities_by_names_query(names, 10)
        ladybug_result = ladybug.build_entities_by_names_query(names, 10)

        # Both use $names parameter
        assert "$names" in neo4j_result
        assert "$names" in ladybug_result

    def test_related_entities_relation_handling_differs(self) -> None:
        neo4j = Neo4jQueryBuilder()
        ladybug = LadybugQueryBuilder()

        config = RelatedEntitiesConfig(
            entity_names=("e1",),
            relation_types=("MENTIONS", "RELATED_TO"),
            max_hops=2,
            limit=10,
        )

        neo4j_result = neo4j.build_related_entities_query(config)
        ladybug_result = ladybug.build_related_entities_query(config)

        # Neo4j uses relation labels in pattern
        assert "-[:MENTIONS|RELATED_TO" in neo4j_result
        # Ladybug uses edge_type property filter
        assert "edge_type IN" in ladybug_result

    def test_key_entities_degree_calculation_differs(self) -> None:
        neo4j = Neo4jQueryBuilder()
        ladybug = LadybugQueryBuilder()

        neo4j_result = neo4j.build_key_entities_query(["550e8400-e29b-41d4-a716-446655440000"], 10)
        ladybug_result = ladybug.build_key_entities_query(
            ["550e8400-e29b-41d4-a716-446655440000"], 10
        )

        # Neo4j includes degree calculation
        assert "degree" in neo4j_result
        # LadybugDB version doesn't include degree
        assert "degree" not in ladybug_result

    def test_community_search_level_handling_differs(self) -> None:
        neo4j = Neo4jQueryBuilder()
        ladybug = LadybugQueryBuilder()

        config = CommunitySearchConfig(level=2, query="test", limit=10)

        neo4j_result = neo4j.build_community_search_query(config)
        ladybug_result = ladybug.build_community_search_query(config)

        # Both use $level parameter
        assert "$level" in neo4j_result
        assert "$level" in ladybug_result

    def test_communities_exist_level_handling_differs(self) -> None:
        neo4j = Neo4jQueryBuilder()
        ladybug = LadybugQueryBuilder()

        neo4j_result = neo4j.build_communities_exist_query(3)
        ladybug_result = ladybug.build_communities_exist_query(3)

        # Both use parameterized level
        assert "$level" in neo4j_result
        assert "$level" in ladybug_result


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_entity_search_config_zero_limit(self) -> None:
        config = EntitySearchConfig(limit=0)
        assert config.limit == 0

    def test_related_entities_config_single_hop(self) -> None:
        config = RelatedEntitiesConfig(max_hops=1)
        assert config.max_hops == 1

    def test_community_search_config_high_level(self) -> None:
        config = CommunitySearchConfig(level=100)
        assert config.level == 100

    def test_empty_entity_names_tuple(self) -> None:
        config = RelatedEntitiesConfig(entity_names=())
        assert len(config.entity_names) == 0

    def test_empty_relation_types_tuple(self) -> None:
        config = RelatedEntitiesConfig(relation_types=())
        assert len(config.relation_types) == 0

    def test_neo4j_builder_empty_names_list(self) -> None:
        builder = Neo4jQueryBuilder()
        result = builder.build_entities_by_names_query([], 10)
        assert "$names" in result

    def test_ladybug_builder_empty_names_list(self) -> None:
        builder = LadybugQueryBuilder()
        result = builder.build_entities_by_names_query([], 10)
        assert "$names" in result

    def test_neo4j_builder_empty_community_ids(self) -> None:
        builder = Neo4jQueryBuilder()
        # Empty list is valid - no validation on empty lists
        result = builder.build_key_entities_query([], 10)
        assert "$community_ids" in result

    def test_ladybug_builder_empty_community_ids(self) -> None:
        builder = LadybugQueryBuilder()
        # Empty list is valid - no validation on empty lists
        result = builder.build_key_entities_query([], 10)
        assert "$community_ids" in result

    def test_neo4j_builder_single_relation_type(self) -> None:
        builder = Neo4jQueryBuilder()
        result = builder.build_relationships_query(["e1"], ["MENTIONS"], 5)
        # Single type should still produce a valid query
        assert "MENTIONS" in result

    def test_query_with_special_characters(self) -> None:
        config = EntitySearchConfig(query="test'with'quotes")
        assert config.query == "test'with'quotes"

    def test_community_id_invalid_rejected(self) -> None:
        builder = Neo4jQueryBuilder()
        # Invalid community IDs should be rejected
        with pytest.raises((InvalidIdentifierError, ValueError)):
            builder.build_community_entities_query("comm-123-abc", 10)


class TestQueryBuilderReturnTypes:
    """Tests ensuring all builder methods return correct types."""

    @pytest.fixture
    def neo4j_builder(self) -> Neo4jQueryBuilder:
        return Neo4jQueryBuilder()

    @pytest.fixture
    def ladybug_builder(self) -> LadybugQueryBuilder:
        return LadybugQueryBuilder()

    def test_all_neo4j_methods_return_str(self, neo4j_builder: Neo4jQueryBuilder) -> None:
        entity_config = EntitySearchConfig()
        related_config = RelatedEntitiesConfig()
        community_config = CommunitySearchConfig()

        assert isinstance(neo4j_builder.build_entity_search_query(entity_config), str)
        assert isinstance(neo4j_builder.build_entities_by_names_query(["e1"], 10), str)
        assert isinstance(neo4j_builder.build_related_entities_query(related_config), str)
        assert isinstance(neo4j_builder.build_relationships_query(["e1"], None, 10), str)
        assert isinstance(neo4j_builder.build_articles_by_entities_query(["e1"], 10), str)
        assert isinstance(neo4j_builder.build_community_search_query(community_config), str)
        assert isinstance(
            neo4j_builder.build_community_entities_query(
                "550e8400-e29b-41d4-a716-446655440000", 10
            ),
            str,
        )
        assert isinstance(
            neo4j_builder.build_key_entities_query(["550e8400-e29b-41d4-a716-446655440000"], 10),
            str,
        )
        assert isinstance(neo4j_builder.build_communities_exist_query(1), str)
        assert isinstance(neo4j_builder.build_communities_exist_query(None), str)

    def test_all_ladybug_methods_return_str(self, ladybug_builder: LadybugQueryBuilder) -> None:
        entity_config = EntitySearchConfig()
        related_config = RelatedEntitiesConfig()
        community_config = CommunitySearchConfig()

        assert isinstance(ladybug_builder.build_entity_search_query(entity_config), str)
        assert isinstance(ladybug_builder.build_entities_by_names_query(["e1"], 10), str)
        assert isinstance(ladybug_builder.build_related_entities_query(related_config), str)
        assert isinstance(ladybug_builder.build_relationships_query(["e1"], None, 10), str)
        assert isinstance(ladybug_builder.build_articles_by_entities_query(["e1"], 10), str)
        assert isinstance(ladybug_builder.build_community_search_query(community_config), str)
        assert isinstance(
            ladybug_builder.build_community_entities_query(
                "550e8400-e29b-41d4-a716-446655440000", 10
            ),
            str,
        )
        assert isinstance(
            ladybug_builder.build_key_entities_query(["550e8400-e29b-41d4-a716-446655440000"], 10),
            str,
        )
        assert isinstance(ladybug_builder.build_communities_exist_query(1), str)
        assert isinstance(ladybug_builder.build_communities_exist_query(None), str)


class TestNeo4jQueryBuilderSecurity:
    """Security tests for Neo4j query builder."""

    @pytest.fixture
    def builder(self) -> Neo4jQueryBuilder:
        return Neo4jQueryBuilder()

    # ── Parameterized Query Tests ───────────────────────────────────────────

    def test_entity_search_uses_parameterized_query(self, builder: Neo4jQueryBuilder) -> None:
        """Entity search should use $query and $limit parameters."""
        config = EntitySearchConfig(query="test", limit=10)
        result = builder.build_entity_search_query(config)
        assert "$query" in result
        assert "$limit" in result

    def test_entities_by_names_uses_parameterized_query(self, builder: Neo4jQueryBuilder) -> None:
        """Entities by names should use $names parameter."""
        result = builder.build_entities_by_names_query(["e1", "e2"], 10)
        assert "$names" in result
        assert "$limit" in result

    def test_related_entities_uses_parameterized_query(self, builder: Neo4jQueryBuilder) -> None:
        """Related entities should use $names and $limit parameters."""
        config = RelatedEntitiesConfig(entity_names=("e1",), max_hops=2, limit=10)
        result = builder.build_related_entities_query(config)
        assert "$names" in result
        assert "$limit" in result

    def test_community_entities_uses_parameterized_query(self, builder: Neo4jQueryBuilder) -> None:
        """Community entities should use $community_id parameter."""
        result = builder.build_community_entities_query("550e8400-e29b-41d4-a716-446655440000", 10)
        assert "$community_id" in result
        assert "$limit" in result

    def test_key_entities_uses_parameterized_query(self, builder: Neo4jQueryBuilder) -> None:
        """Key entities should use $community_ids parameter."""
        result = builder.build_key_entities_query(["550e8400-e29b-41d4-a716-446655440000"], 10)
        assert "$community_ids" in result
        assert "$limit" in result

    # ── UUID Validation Tests ────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "community_id",
        [
            "550e8400-e29b-41d4-a716-446655440000",
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            "00000000-0000-0000-0000-000000000000",
        ],
    )
    def test_community_entities_accepts_valid_uuid(
        self, builder: Neo4jQueryBuilder, community_id: str
    ) -> None:
        """Valid UUIDs should be accepted."""
        result = builder.build_community_entities_query(community_id, 10)
        assert "$community_id" in result

    @pytest.mark.parametrize(
        "community_id",
        [
            "not-a-uuid",
            "12345",
            "550e8400-e29b-41d4-a716",  # Truncated
            "'; MATCH (n) DETACH DELETE n //",
            "../../../etc/passwd",
        ],
    )
    def test_community_entities_rejects_invalid_uuid(
        self, builder: Neo4jQueryBuilder, community_id: str
    ) -> None:
        """Invalid UUIDs should be rejected."""
        with pytest.raises((InvalidIdentifierError, ValueError)):
            builder.build_community_entities_query(community_id, 10)

    @pytest.mark.parametrize(
        "community_id",
        [
            "'; MATCH (n) DETACH DELETE n //",
            "550e8400']; DROP TABLE users; //",
        ],
    )
    def test_key_entities_rejects_malicious_uuid(
        self, builder: Neo4jQueryBuilder, community_id: str
    ) -> None:
        """Malicious UUIDs should be rejected in key_entities_query."""
        with pytest.raises((InvalidIdentifierError, ValueError)):
            builder.build_key_entities_query([community_id], 10)

    # ── Edge Type Validation Tests ──────────────────────────────────────────

    @pytest.mark.parametrize(
        "relation_type",
        [
            "KNOWS",
            "RELATED_TO",
            "PARTNERS_WITH",
            "中文关系",
        ],
    )
    def test_related_entities_accepts_valid_relation_types(
        self, builder: Neo4jQueryBuilder, relation_type: str
    ) -> None:
        """Valid relation types should be accepted."""
        config = RelatedEntitiesConfig(
            entity_names=("e1",),
            relation_types=(relation_type,),
            max_hops=2,
            limit=10,
        )
        result = builder.build_related_entities_query(config)
        assert relation_type in result

    @pytest.mark.parametrize(
        "relation_type",
        [
            "knows",  # Lowercase not allowed
            "KNOWS']; MATCH (n) DETACH DELETE n //",
            "123INVALID",
            "invalid-type",
            "REL`] DETACH DELETE n //",
        ],
    )
    def test_related_entities_rejects_malicious_relation_types(
        self, builder: Neo4jQueryBuilder, relation_type: str
    ) -> None:
        """Malicious relation types should be rejected."""
        config = RelatedEntitiesConfig(
            entity_names=("e1",),
            relation_types=(relation_type,),
            max_hops=2,
            limit=10,
        )
        with pytest.raises((InvalidIdentifierError, ValueError)):
            builder.build_related_entities_query(config)

    @pytest.mark.parametrize(
        "relation_type",
        [
            "KNOWS']; DETACH DELETE n //",
            "RELATED_TO`; MATCH (n) DELETE n //",
        ],
    )
    def test_relationships_query_rejects_malicious_types(
        self, builder: Neo4jQueryBuilder, relation_type: str
    ) -> None:
        """Malicious relation types in relationships_query should be rejected."""
        with pytest.raises((InvalidIdentifierError, ValueError)):
            builder.build_relationships_query(["e1"], [relation_type], 10)

    # ── Max Hops Validation Tests ───────────────────────────────────────────

    def test_related_entities_validates_max_hops_lower_bound(
        self, builder: Neo4jQueryBuilder
    ) -> None:
        """max_hops < 1 should be rejected."""
        config = RelatedEntitiesConfig(entity_names=("e1",), max_hops=0, limit=10)
        with pytest.raises(ValueError, match="max_hops"):
            builder.build_related_entities_query(config)

    def test_related_entities_validates_max_hops_upper_bound(
        self, builder: Neo4jQueryBuilder
    ) -> None:
        """max_hops > 5 should be rejected."""
        config = RelatedEntitiesConfig(entity_names=("e1",), max_hops=6, limit=10)
        with pytest.raises(ValueError, match="max_hops"):
            builder.build_related_entities_query(config)

    # ── Limit Validation Tests ──────────────────────────────────────────────

    def test_community_entities_validates_limit(self, builder: Neo4jQueryBuilder) -> None:
        """limit < 1 should be rejected."""
        with pytest.raises(ValueError, match="limit must be positive"):
            builder.build_community_entities_query("550e8400-e29b-41d4-a716-446655440000", 0)

    def test_key_entities_validates_limit(self, builder: Neo4jQueryBuilder) -> None:
        """limit < 1 should be rejected."""
        with pytest.raises(ValueError, match="limit must be positive"):
            builder.build_key_entities_query(["550e8400-e29b-41d4-a716-446655440000"], 0)


class TestLadybugQueryBuilderSecurity:
    """Security tests for LadybugDB query builder."""

    @pytest.fixture
    def builder(self) -> LadybugQueryBuilder:
        return LadybugQueryBuilder()

    # ── UUID Validation Tests ────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "community_id",
        [
            "550e8400-e29b-41d4-a716-446655440000",
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        ],
    )
    def test_community_entities_accepts_valid_uuid(
        self, builder: LadybugQueryBuilder, community_id: str
    ) -> None:
        """Valid UUIDs should be accepted."""
        result = builder.build_community_entities_query(community_id, 10)
        assert "$community_id" in result

    @pytest.mark.parametrize(
        "community_id",
        [
            "not-a-uuid",
            "'; SELECT * FROM users; --",
            "../../../etc/passwd",
        ],
    )
    def test_community_entities_rejects_invalid_uuid(
        self, builder: LadybugQueryBuilder, community_id: str
    ) -> None:
        """Invalid UUIDs should be rejected."""
        with pytest.raises((InvalidIdentifierError, ValueError)):
            builder.build_community_entities_query(community_id, 10)

    # ── Edge Type Validation Tests ──────────────────────────────────────────

    @pytest.mark.parametrize(
        "relation_type",
        [
            "KNOWS",
            "RELATED_TO",
            "PARTNERS_WITH",
        ],
    )
    def test_related_entities_accepts_valid_relation_types(
        self, builder: LadybugQueryBuilder, relation_type: str
    ) -> None:
        """Valid relation types should be accepted."""
        config = RelatedEntitiesConfig(
            entity_names=("e1",),
            relation_types=(relation_type,),
            max_hops=2,
            limit=10,
        )
        result = builder.build_related_entities_query(config)
        assert "$relation_types" in result or relation_type in result

    @pytest.mark.parametrize(
        "relation_type",
        [
            "knows",
            "KNOWS']; SELECT * FROM users; --",
            "invalid-type",
        ],
    )
    def test_related_entities_rejects_malicious_relation_types(
        self, builder: LadybugQueryBuilder, relation_type: str
    ) -> None:
        """Malicious relation types should be rejected."""
        config = RelatedEntitiesConfig(
            entity_names=("e1",),
            relation_types=(relation_type,),
            max_hops=2,
            limit=10,
        )
        with pytest.raises((InvalidIdentifierError, ValueError)):
            builder.build_related_entities_query(config)

    # ── Max Hops Validation Tests ───────────────────────────────────────────

    def test_related_entities_validates_max_hops(self, builder: LadybugQueryBuilder) -> None:
        """max_hops out of range should be rejected."""
        config = RelatedEntitiesConfig(entity_names=("e1",), max_hops=0, limit=10)
        with pytest.raises(ValueError, match="max_hops"):
            builder.build_related_entities_query(config)
