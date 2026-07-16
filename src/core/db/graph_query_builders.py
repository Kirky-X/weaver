# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Database-agnostic query builders for graph database operations.

Provides a QueryBuilder pattern that abstracts database-specific graph query syntax,
supporting both Neo4j (Cypher) and LadybugDB backends.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from core.db.safe_query import (
    validate_edge_type,
    validate_relation_types,
    validate_uuid,
)


class GraphDatabaseType(str, Enum):
    """Supported graph database types."""

    NEO4J = "neo4j"
    LADYBUG = "ladybug"


# === Search Config Dataclasses (migrated from graph_query.py) ===


@dataclass(frozen=True)
class EntitySearchConfig:
    """Configuration for entity search query.

    Attributes:
        query: Search query string.
        limit: Maximum results.
        use_aliases: Whether to search in aliases.
    """

    query: str = ""
    limit: int = 20
    use_aliases: bool = True


@dataclass(frozen=True)
class RelatedEntitiesConfig:
    """Configuration for related entities query.

    Attributes:
        entity_names: Source entity names.
        relation_types: Optional relation types to filter.
        max_hops: Maximum traversal depth.
        limit: Maximum results.
    """

    entity_names: tuple[str, ...] = ()
    relation_types: tuple[str, ...] = ()
    max_hops: int = 2
    limit: int = 20


@dataclass(frozen=True)
class CommunitySearchConfig:
    """Configuration for community search query.

    Attributes:
        level: Community hierarchy level.
        query: Optional text search query.
        limit: Maximum results.
    """

    level: int = 0
    query: str = ""
    limit: int = 10


@runtime_checkable
class GraphQueryBuilder(Protocol):
    """Protocol for database-specific graph query builders.

    Defines the interface for building database-agnostic graph operations.
    Implementations must handle database-specific query syntax differences.
    """

    @property
    def database_type(self) -> GraphDatabaseType:
        """Get the database type for this builder."""
        ...

    # === Capability Detection ===

    def supports_element_id(self) -> bool:
        """Check if database supports elementId() function."""
        ...

    def supports_datetime_function(self) -> bool:
        """Check if database supports datetime() function."""
        ...

    def supports_detach_delete(self) -> bool:
        """Check if database supports DETACH DELETE syntax."""
        ...

    def supports_list_comprehension(self) -> bool:
        """Check if database supports Cypher list comprehension syntax."""
        ...

    # === Expression Builders ===

    def entity_id_expression(self, node_var: str) -> str:
        """Build entity ID expression.

        Args:
            node_var: Variable name for the node in Cypher query.

        Returns:
            Cypher expression for entity ID (elementId(e) or e.id).
        """
        ...

    def weight_expression(self, rel_var: str) -> str:
        """Build weight expression for relationships.

        Args:
            rel_var: Variable name for the relationship in Cypher query.

        Returns:
            Cypher expression for relationship weight.
        """
        ...

    # === Metrics Queries ===

    def build_component_neighbors_query(self) -> str:
        """Build query to get entity neighbors for component analysis."""
        ...

    def build_degree_query(self) -> str:
        """Build query to calculate entity degrees."""
        ...

    def build_edges_with_weight_query(self) -> str:
        """Build query to get edges with weights for modularity."""
        ...

    # === Entity Repository Queries ===

    def build_get_entity_query(self) -> str:
        """Build query to get entity by canonical name and type."""
        ...

    def build_get_entity_relations_query(self) -> str:
        """Build query to get entity relationships."""
        ...

    def build_get_related_entities_query(self) -> str:
        """Build query to get entities mentioned in same articles."""
        ...

    def build_get_entity_articles_query(self) -> str:
        """Build query to get articles mentioning an entity."""
        ...

    def build_get_article_graph_query(self) -> str:
        """Build query to get article with its entities."""
        ...

    def build_get_article_entities_query(self) -> str:
        """Build query to get entities mentioned in an article."""
        ...

    def build_get_article_relationships_query(self) -> str:
        """Build query to get relationships between entities in an article."""
        ...

    def build_get_related_articles_query(self) -> str:
        """Build query to get related articles."""
        ...

    def build_get_relation_types_query(self, entity_type: str | None = None) -> str:
        """Build query to get relation types for an entity.

        Args:
            entity_type: Optional entity type filter. When None, matches
                by canonical_name only (cross-type lookup).
        """
        ...

    def build_find_by_relation_types_query(
        self, relation_types: list[str] | None, entity_type: str | None = None
    ) -> str:
        """Build query to find entities by relation types."""

    # === Visualization Queries ===

    def build_visualization_nodes_query(self) -> str:
        """Build query to get nodes for graph visualization."""
        ...

    def build_visualization_edges_query(self) -> str:
        """Build query to get edges for graph visualization."""
        ...

    def build_subgraph_nodes_query(self, hop_pattern: str, include_types: bool) -> str:
        """Build query to get nodes for subgraph extraction.

        Args:
            hop_pattern: Hop pattern like '*1..2' for variable-length path.
            include_types: Whether to include type filtering clause.
        """
        ...

    def build_subgraph_edges_query(self) -> str:
        """Build query to get edges for subgraph visualization."""
        ...

    def build_traverse_query(
        self,
        max_depth: int = 3,
        relation_types: list[str] | None = None,
        return_paths: bool = False,
        mode: str = "full",
        min_confidence: float | None = None,
    ) -> str:
        """Build query for multi-hop graph traversal.

        Args:
            max_depth: Maximum traversal depth (embedded in query pattern).
            relation_types: Optional list of relation types to filter.
            return_paths: Whether to return complete paths.
            mode: Traversal mode - 'full' or 'aggregate'.
            min_confidence: Minimum confidence score filter.
        """
        ...

    # === Search & Community Query Methods (migrated from graph_query.py) ===

    def build_entity_search_query(self, config: EntitySearchConfig) -> str:
        """Build query to find entities by name/alias search.

        Args:
            config: Search configuration.

        Returns:
            Query string with $query and $limit parameters.
        """
        ...

    def build_entities_by_names_query(self, names: list[str], limit: int) -> str:
        """Build query to get entities by canonical names.

        Args:
            names: List of entity names to fetch.
            limit: Maximum results.

        Returns:
            Query string with $names parameter.
        """
        ...

    def build_related_entities_query(self, config: RelatedEntitiesConfig) -> str:
        """Build query to get entities related to source entities.

        Args:
            config: Related entities configuration.

        Returns:
            Query string with $names and $limit parameters.
        """
        ...

    def build_relationships_query(
        self,
        entity_names: list[str],
        relation_types: list[str] | None,
        limit: int,
    ) -> str:
        """Build query to get relationships involving entities.

        Args:
            entity_names: Source entity names.
            relation_types: Optional relation types to filter.
            limit: Maximum results.

        Returns:
            Query string.
        """
        ...

    def build_articles_by_entities_query(
        self,
        entity_names: list[str],
        limit: int,
    ) -> str:
        """Build query to get articles mentioning entities.

        Args:
            entity_names: Entity names to search for.
            limit: Maximum results.

        Returns:
            Query string.
        """
        ...

    def build_community_search_query(
        self,
        config: CommunitySearchConfig,
    ) -> str:
        """Build query to find communities by level and optional text.

        Args:
            config: Community search configuration.

        Returns:
            Query string.
        """
        ...

    def build_community_entities_query(
        self,
        community_id: str,
        limit: int,
    ) -> str:
        """Build query to get entities in a community.

        Args:
            community_id: Community ID.
            limit: Maximum results.

        Returns:
            Query string.
        """
        ...

    def build_key_entities_query(
        self,
        community_ids: list[str],
        limit: int,
    ) -> str:
        """Build query to get key entities from multiple communities.

        Args:
            community_ids: List of community IDs.
            limit: Maximum results.

        Returns:
            Query string.
        """
        ...

    def build_communities_exist_query(self, level: int | None) -> str:
        """Build query to check if communities exist.

        Args:
            level: Optional level filter.

        Returns:
            Query string returning count.
        """
        ...

    def build_vector_search_communities_query(
        self,
        level: int,
        limit: int,
    ) -> str | None:
        """Build query to search communities using vector similarity.

        Args:
            level: Community hierarchy level.
            limit: Maximum results.

        Returns:
            Query string with $embedding, $level, $limit parameters,
            or None if vector search is not supported (e.g., LadybugDB).
        """
        ...

    def build_cross_community_relationships_query(
        self,
        community_ids: list[str],
    ) -> str:
        """Build query to get relationships connecting different communities.

        Args:
            community_ids: List of community IDs to search within.

        Returns:
            Query string with $community_ids parameter.
        """
        ...

    def build_entity_article_fallback_query(
        self,
        tokens: list[str],
        limit: int,
    ) -> str:
        """Build query for entity-article fallback when no communities match.

        Args:
            tokens: Search tokens extracted from query.
            limit: Maximum results.

        Returns:
            Query string with $tokens and $limit parameters.
        """
        ...

    def build_entity_article_fallback_with_description_query(
        self,
        tokens: list[str],
        limit: int,
    ) -> str:
        """Build query for entity-article fallback searching name AND description.

        Used for Chinese queries where token-based matching on description
        is needed in addition to canonical_name.

        Args:
            tokens: Search tokens extracted from query.
            limit: Maximum results.

        Returns:
            Query string with $tokens and $limit parameters.
        """
        ...

    def build_articles_by_text_query(
        self,
        limit: int,
    ) -> str:
        """Build query to search articles by title text match.

        Args:
            limit: Maximum results.

        Returns:
            Query string with $query and $limit parameters.
        """
        ...


class Neo4jQueryBuilder:
    """Neo4j (Cypher) implementation of GraphQueryBuilder."""

    @property
    def database_type(self) -> GraphDatabaseType:
        """Get Neo4j database type."""
        return GraphDatabaseType.NEO4J

    # === Capability Detection ===

    def supports_element_id(self) -> bool:
        """Neo4j supports elementId()."""
        return True

    def supports_datetime_function(self) -> bool:
        """Neo4j supports datetime()."""
        return True

    def supports_detach_delete(self) -> bool:
        """Neo4j supports DETACH DELETE."""
        return True

    def supports_list_comprehension(self) -> bool:
        """Neo4j supports Cypher list comprehension."""
        return True

    # === Expression Builders ===

    def entity_id_expression(self, node_var: str) -> str:
        """Neo4j uses elementId() function."""
        return f"elementId({node_var})"

    def weight_expression(self, rel_var: str) -> str:
        """Neo4j stores weight on relationship."""
        return f"coalesce({rel_var}.weight, 1.0)"

    # === Metrics Queries ===

    def build_component_neighbors_query(self) -> str:
        """Build Neo4j component query matching all Entity-to-Entity relationships.

        Uses untyped ``--`` pattern instead of ``[:RELATED_TO]`` since actual
        relationship types are Chinese-named (发布, 参与, etc.) or English
        (EVENT_FOLLOWED_BY).  Article-to-Entity edges (HAS_ENTITY, MENTIONS)
        are automatically excluded because they connect to Article nodes.
        """
        return """
        MATCH (e:Entity)
        OPTIONAL MATCH (e)--(connected:Entity)
        WITH e, collect(DISTINCT connected) AS neighbors
        RETURN e.canonical_name AS entity,
               [n IN neighbors | n.canonical_name] AS neighbors,
               e.type AS type
        """

    def build_degree_query(self) -> str:
        """Build Neo4j degree query counting all Entity-to-Entity relationships.

        Excludes Article nodes and MENTIONS (which is counted separately as
        mention_count) so that in_degree/out_degree reflect semantic
        Entity↔Entity edges only.
        """
        return """
        MATCH (e:Entity)
        OPTIONAL MATCH (e)-[r_out]->(connected_out)
        WHERE NOT connected_out:Article
        OPTIONAL MATCH (connected_in)-[r_in]->(e)
        WHERE NOT connected_in:Article AND type(r_in) <> 'MENTIONS'
        OPTIONAL MATCH ()-[m:MENTIONS]->(e)
        WITH e,
             count(DISTINCT r_out) AS out_degree,
             count(DISTINCT r_in) AS in_degree,
             count(DISTINCT m) AS mention_count
        RETURN elementId(e) AS entity_id,
               e.canonical_name AS name,
               e.type AS type,
               out_degree,
               in_degree,
               mention_count,
               (out_degree + in_degree) AS total_degree
        ORDER BY total_degree DESC
        """

    def build_edges_with_weight_query(self) -> str:
        """Build Neo4j edges query."""
        return """
        MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
        RETURN e1.canonical_name AS source,
               e2.canonical_name AS target,
               coalesce(r.weight, 1.0) AS weight
        """

    # === Entity Repository Queries ===

    def build_get_entity_query(self) -> str:
        """Build Neo4j query to get entity by canonical name or alias."""
        # Support lookup by canonical_name OR alias
        return """
            MATCH (e:Entity)
            WHERE e.canonical_name = $name OR $name IN e.aliases
            RETURN e.id as id, e.canonical_name as canonical_name, e.type as type,
                   e.aliases as aliases, e.description as description,
                   e.updated_at as updated_at
        """

    def build_get_entity_relations_query(self) -> str:
        """Build Neo4j query to get entity relationships."""
        # Support lookup by canonical_name OR alias
        # Use untyped pattern -[r]-> to match all semantic relationships
        # Exclude system metadata relations (MENTIONS, FOLLOWED_BY)
        return """
            MATCH (e:Entity)
            WHERE e.canonical_name = $name OR $name IN e.aliases
            MATCH (e)-[r]->(target:Entity)
            WHERE type(r) <> 'MENTIONS' AND type(r) <> 'FOLLOWED_BY'
            RETURN target.canonical_name as target, type(r) as relation_type,
                   r.source_article_id as source_article_id, r.created_at as created_at
            ORDER BY r.created_at DESC
            LIMIT $limit
        """

    def build_get_related_entities_query(self) -> str:
        """Build Neo4j query to get entities mentioned in same articles."""
        # Support lookup by canonical_name OR alias
        return """
            MATCH (e:Entity)
            WHERE e.canonical_name = $name OR $name IN e.aliases
            MATCH (e)-[:MENTIONS]-(a:Article)-[:MENTIONS]-(re:Entity)
            WHERE re.canonical_name <> e.canonical_name
            RETURN DISTINCT re.id as id, re.canonical_name as canonical_name,
                   re.type as type, re.aliases as aliases,
                   re.description as description, re.created_at as created_at,
                   re.updated_at as updated_at
            LIMIT $limit
        """

    def build_get_entity_articles_query(self) -> str:
        """Build Neo4j query to get articles mentioning an entity.

        MENTIONS edge direction is (Article)-[:MENTIONS]->(Entity), so we
        traverse from Entity back to Article via incoming MENTIONS edges.
        """
        # Support lookup by canonical_name OR alias
        return """
            MATCH (e:Entity)
            WHERE e.canonical_name = $name OR $name IN e.aliases
            MATCH (a:Article)-[:MENTIONS]->(e)
            RETURN a.pg_id as id, a.title as title, a.category as category,
                   a.publish_time as publish_time, a.score as score
            ORDER BY a.publish_time DESC
            LIMIT $limit
        """

    def build_get_article_graph_query(self) -> str:
        """Build Neo4j query to get article node."""
        return """
            MATCH (a:Article {pg_id: $id})
            RETURN a.pg_id as id, a.title as title, a.category as category,
                   a.publish_time as publish_time, a.score as score
        """

    def build_get_article_entities_query(self) -> str:
        """Build Neo4j query to get entities mentioned in an article."""
        return """
            MATCH (a:Article {pg_id: $id})-[r:MENTIONS]->(e:Entity)
            RETURN e.id as id, e.canonical_name as canonical_name, e.type as type,
                   e.aliases as aliases, e.description as description,
                   e.created_at as created_at, e.updated_at as updated_at
        """

    def build_get_article_relationships_query(self) -> str:
        """Build Neo4j query to get relationships between entities in an article."""
        return """
            MATCH (a:Article {pg_id: $id})-[:MENTIONS]->(e1:Entity)
            MATCH (e1)-[r]->(e2:Entity)
            WHERE type(r) <> 'MENTIONS' AND type(r) <> 'HAS_ENTITY'
              AND (a)-[:MENTIONS]->(e2)
            RETURN e1.canonical_name as source, e2.canonical_name as target,
                   type(r) as relation_type,
                   r.description as description,
                   coalesce(r.weight, 1.0) as weight,
                   r.created_at as created_at
        """

    def build_get_related_articles_query(self) -> str:
        """Build Neo4j query to get related articles via shared entities.

        Finds articles that mention the same entities, ranked by overlap count.
        """
        return """
            MATCH (a:Article {pg_id: $id})-[:MENTIONS]->(e:Entity)<-[:MENTIONS]-(ra:Article)
            WHERE ra.pg_id <> $id
            RETURN ra.pg_id as id, ra.title as title, ra.category as category,
                   ra.publish_time as publish_time, ra.score as score,
                   count(DISTINCT e) as shared_entities
            ORDER BY shared_entities DESC, ra.publish_time DESC
            LIMIT 10
        """

    def build_get_relation_types_query(self, entity_type: str | None = None) -> str:
        """Build Neo4j query to get relation types for an entity.

        When entity_type is None, matches by canonical_name only (cross-type
        lookup) — Neo4j's `{type: null}` pattern would never match, so we
        must omit the type key entirely.

        Args:
            entity_type: Optional entity type filter.
        """
        entity_pattern = (
            "{canonical_name: $name, type: $type}"
            if entity_type is not None
            else "{canonical_name: $name}"
        )
        return f"""
            MATCH (e:Entity {entity_pattern})-[r]-(other:Entity)
            WHERE type(r) <> 'MENTIONS' AND type(r) <> 'FOLLOWED_BY'
              AND (other.pruned IS NULL OR NOT other.pruned)
            RETURN type(r) AS relation_type,
                   count(DISTINCT other) AS target_count,
                   head(collect(DISTINCT
                       CASE WHEN (e)-[r]->(other) THEN 'outgoing' ELSE 'incoming' END
                   )) AS primary_direction
            ORDER BY target_count DESC
        """

    def build_find_by_relation_types_query(
        self, relation_types: list[str] | None, entity_type: str | None = None
    ) -> str:
        """Build Neo4j query to find entities by relation types.

        Weight is computed dynamically as co-occurrence article count.
        When entity_type is None, matches only by canonical_name.

        Args:
            relation_types: Optional list of edge types to filter. Each type
                is validated against whitelist pattern before use.
            entity_type: Optional entity type filter.

        Returns:
            Cypher query string with parameterized values.
        """
        type_clause = (
            "{canonical_name: $name, type: $type}"
            if entity_type is not None
            else "{canonical_name: $name}"
        )
        if not relation_types:
            return f"""
                MATCH (e:Entity {type_clause})-[r]-(other:Entity)
                WHERE type(r) <> 'MENTIONS' AND type(r) <> 'FOLLOWED_BY'
                  AND (other.pruned IS NULL OR NOT other.pruned)
                OPTIONAL MATCH (a:Article)-[:MENTIONS]->(e)
                WHERE (a)-[:MENTIONS]->(other)
                WITH type(r) AS relation_type,
                     CASE WHEN (e)-[r]->(other) THEN 'outgoing' ELSE 'incoming' END AS direction,
                     other.canonical_name AS target_name,
                     other.type AS target_type,
                     other.description AS target_description,
                     coalesce(r.weight, 1.0) AS stored_weight,
                     count(DISTINCT a) AS shared_articles
                RETURN relation_type,
                       direction,
                       target_name,
                       target_type,
                       target_description,
                       CASE WHEN stored_weight > 1.0 THEN stored_weight
                            WHEN shared_articles > 0 THEN shared_articles * 1.0
                            ELSE stored_weight END AS weight
                ORDER BY weight DESC
                LIMIT $limit
            """
        else:
            # Validate edge types against whitelist to prevent injection
            validated_types = validate_relation_types(relation_types)
            # Build safe filter using validated identifiers
            type_filters = " OR ".join(f"type(r) = '{rt}'" for rt in validated_types)
            return f"""
                MATCH (e:Entity {type_clause})-[r]-(other:Entity)
                WHERE ({type_filters})
                  AND type(r) <> 'MENTIONS' AND type(r) <> 'FOLLOWED_BY'
                  AND NOT other.pruned = true
                OPTIONAL MATCH (a:Article)-[:MENTIONS]->(e)
                WHERE (a)-[:MENTIONS]->(other)
                WITH type(r) AS relation_type,
                     CASE WHEN (e)-[r]->(other) THEN 'outgoing' ELSE 'incoming' END AS direction,
                     other.canonical_name AS target_name,
                     other.type AS target_type,
                     other.description AS target_description,
                     coalesce(r.weight, 1.0) AS stored_weight,
                     count(DISTINCT a) AS shared_articles
                RETURN relation_type,
                       direction,
                       target_name,
                       target_type,
                       target_description,
                       CASE WHEN stored_weight > 1.0 THEN stored_weight
                            WHEN shared_articles > 0 THEN shared_articles * 1.0
                            ELSE stored_weight END AS weight
                ORDER BY weight DESC
                LIMIT $limit
            """

    # === Visualization Queries ===

    def build_visualization_nodes_query(self) -> str:
        """Build Neo4j query to get nodes for graph visualization.

        Degree counts Entity-Entity business relations only (参与/位于/任职于/etc.),
        excluding structural MENTIONS/HAS_ENTITY (Entity↔Article) and
        EVENT_FOLLOWED_BY (Event↔Event) which are not entity semantics.
        """
        return """
        MATCH (e:Entity)
        RETURN e.canonical_name AS id,
               e.canonical_name AS label,
               e.type AS type,
               e.description AS description,
               size([(e)-[r]-(other:Entity)
                     WHERE NOT type(r) IN ['MENTIONS','HAS_ENTITY','EVENT_FOLLOWED_BY']
                     | 1]) AS degree
        ORDER BY degree DESC
        LIMIT $limit
        """

    def build_visualization_edges_query(self) -> str:
        """Build Neo4j query to get edges for graph visualization.

        Returns Entity-Entity business relations (参与/位于/任职于/etc.) only,
        excluding structural MENTIONS/HAS_ENTITY/EVENT_FOLLOWED_BY.
        """
        return """
        MATCH (e1:Entity)-[r]->(e2:Entity)
        WHERE e1.canonical_name IN $node_ids AND e2.canonical_name IN $node_ids
          AND NOT type(r) IN ['MENTIONS','HAS_ENTITY','EVENT_FOLLOWED_BY']
        RETURN e1.canonical_name AS source,
               e2.canonical_name AS target,
               type(r) AS relation_type,
               r.weight AS weight
        LIMIT $edge_limit
        """

    def build_subgraph_nodes_query(self, hop_pattern: str, include_types: bool) -> str:
        """Build Neo4j query to get nodes for subgraph extraction."""
        if include_types:
            return f"""
            MATCH path = (center:Entity {{canonical_name: $center}})-[r{hop_pattern}]-(related:Entity)
            WHERE related.type IN $include_types
            WITH collect(DISTINCT related) AS related_nodes
            MATCH (center:Entity {{canonical_name: $center}})
            WITH center + related_nodes AS all_nodes
            UNWIND all_nodes AS node
            MATCH (node)-[r]-(other:Entity)
            WHERE other IN all_nodes
            RETURN DISTINCT node.canonical_name AS id,
                   node.canonical_name AS label,
                   node.type AS type,
                   node.description AS description
            LIMIT 200
            """
        else:
            return f"""
            MATCH path = (center:Entity {{canonical_name: $center}})-[r{hop_pattern}]-(related:Entity)
            WITH collect(DISTINCT related) AS related_nodes
            MATCH (center:Entity {{canonical_name: $center}})
            WITH center + related_nodes AS all_nodes
            UNWIND all_nodes AS node
            MATCH (node)-[r]-(other:Entity)
            WHERE other IN all_nodes
            RETURN DISTINCT node.canonical_name AS id,
                   node.canonical_name AS label,
                   node.type AS type,
                   node.description AS description
            LIMIT 200
            """

    def build_subgraph_edges_query(self) -> str:
        """Build Neo4j query to get edges for subgraph visualization."""
        return """
        MATCH (e1:Entity)-[r]->(e2:Entity)
        WHERE e1.canonical_name IN $node_ids AND e2.canonical_name IN $node_ids
        RETURN e1.canonical_name AS source,
               e2.canonical_name AS target,
               type(r) AS relation_type,
               r.weight AS weight
        LIMIT 500
        """

    def build_traverse_query(
        self,
        max_depth: int = 3,
        relation_types: list[str] | None = None,
        return_paths: bool = False,
        mode: str = "full",
        min_confidence: float | None = None,
    ) -> str:
        """Build Neo4j query for multi-hop graph traversal."""
        confidence_filter = (
            f" AND coalesce(r.weight, 1.0) >= {min_confidence}"
            if min_confidence is not None
            else ""
        )

        if mode == "aggregate":
            return f"""
            MATCH (center:Entity {{canonical_name: $center}})
            MATCH path = (center)-[r*1..{max_depth}]-(other:Entity)
            WHERE type(r[-1]) <> 'MENTIONS' AND type(r[-1]) <> 'FOLLOWED_BY'
            {confidence_filter}
            WITH count(DISTINCT other) AS total_nodes,
                 count(DISTINCT r) AS total_edges,
                 type(r[-1]) AS relation_type
            RETURN total_nodes, total_edges,
                   relation_type,
                   count(*) AS type_count
            """

        if return_paths:
            return f"""
            MATCH (center:Entity {{canonical_name: $center}})
            MATCH path = (center)-[r*1..{max_depth}]-(other:Entity)
            WHERE type(r[-1]) <> 'MENTIONS' AND type(r[-1]) <> 'FOLLOWED_BY'
            {confidence_filter}
            RETURN other.canonical_name AS node_name,
                   elementId(other) AS node_id,
                   other.type AS node_type,
                   other.description AS node_description,
                   startNode(r[-1]).canonical_name AS source,
                   endNode(r[-1]).canonical_name AS target,
                   type(r[-1]) AS relation_type,
                   [n IN nodes(path) | n.canonical_name] AS path_nodes,
                   [rel IN relationships(path) | {{
                       source: startNode(rel).canonical_name,
                       target: endNode(rel).canonical_name,
                       relation_type: type(rel)
                   }}] AS path_edges
            LIMIT $limit
            """

        return f"""
        MATCH (center:Entity {{canonical_name: $center}})
        MATCH (center)-[r*1..{max_depth}]-(other:Entity)
        WHERE type(r[-1]) <> 'MENTIONS' AND type(r[-1]) <> 'FOLLOWED_BY'
        {confidence_filter}
        RETURN DISTINCT other.canonical_name AS node_name,
               elementId(other) AS node_id,
               other.type AS node_type,
               other.description AS node_description,
               startNode(r[-1]).canonical_name AS source,
               endNode(r[-1]).canonical_name AS target,
               type(r[-1]) AS relation_type
        LIMIT $limit
        """

    # === Search & Community Query Methods (migrated from graph_query.py) ===

    def build_entity_search_query(self, config: EntitySearchConfig) -> str:
        if config.use_aliases:
            return """
            MATCH (e:Entity)
            WHERE toLower(e.canonical_name) CONTAINS $query
               OR any(alias IN e.aliases WHERE toLower(alias) CONTAINS $query)
            RETURN e.canonical_name AS name
            LIMIT $limit
            """
        return """
        MATCH (e:Entity)
        WHERE toLower(e.canonical_name) CONTAINS $query
        RETURN e.canonical_name AS name
        LIMIT $limit
        """

    def build_entities_by_names_query(self, names: list[str], limit: int) -> str:
        return """
        MATCH (e:Entity)
        WHERE e.canonical_name IN $names
        RETURN e.canonical_name AS canonical_name,
               e.type AS type,
               e.description AS description,
               e.aliases AS aliases
        LIMIT $limit
        """

    def build_related_entities_query(self, config: RelatedEntitiesConfig) -> str:
        # Validate max_hops to prevent resource exhaustion
        if config.max_hops < 1 or config.max_hops > 5:
            raise ValueError(f"max_hops must be between 1 and 5, got {config.max_hops}")

        # Build safe relation pattern - validate relation types if provided
        if config.relation_types:
            for rt in config.relation_types:
                validate_edge_type(rt)
            rel_types_str = "|".join(config.relation_types)
            rel_pattern = f"-[:{rel_types_str}*1..{config.max_hops}]-"
        else:
            rel_pattern = f"-[:RELATED_TO*1..{config.max_hops}]-"

        return f"""
        MATCH (e:Entity){rel_pattern}(related:Entity)
        WHERE e.canonical_name IN $names
        RETURN DISTINCT related.canonical_name AS canonical_name,
               related.type AS type,
               count(e) AS connection_count
        ORDER BY connection_count DESC
        LIMIT $limit
        """

    def build_relationships_query(
        self,
        entity_names: list[str],
        relation_types: list[str] | None,
        limit: int,
    ) -> str:
        if relation_types:
            # Validate relation types
            for rt in relation_types:
                validate_edge_type(rt)

            # Use UNION with typed relations
            queries = []
            for rt in relation_types:
                queries.append(f"""
                    MATCH (e1:Entity)-[r:{rt}]->(e2:Entity)
                    WHERE e1.canonical_name IN $names OR e2.canonical_name IN $names
                    RETURN e1.canonical_name AS source_name,
                           e2.canonical_name AS target_name,
                           '{rt}' AS relation_type
                """)
            return "\n UNION ALL \n".join(queries) + "\n LIMIT $limit"

        return """
        MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
        WHERE e1.canonical_name IN $names OR e2.canonical_name IN $names
        RETURN e1.canonical_name AS source_name,
               e2.canonical_name AS target_name,
               r.relation_type AS relation_type
        ORDER BY coalesce(r.weight, 1.0) DESC
        LIMIT $limit
        """

    def build_articles_by_entities_query(
        self,
        entity_names: list[str],
        limit: int,
    ) -> str:
        return """
        MATCH (a:Article)-[:MENTIONS]->(e:Entity)
        WHERE e.canonical_name IN $names
        RETURN DISTINCT a.pg_id AS id,
               a.title AS title,
               a.summary AS summary,
               a.publish_time AS publish_time
        ORDER BY a.publish_time DESC
        LIMIT $limit
        """

    def build_community_search_query(
        self,
        config: CommunitySearchConfig,
    ) -> str:
        if config.query:
            return """
            MATCH (c:Community)
            WHERE c.level >= $level
              AND (toLower(c.title) CONTAINS $query
                   OR toLower(c.summary) CONTAINS $query)
            RETURN c.id AS id,
                   c.title AS title,
                   c.summary AS summary,
                   c.rank AS rank,
                   c.entity_count AS entity_count
            ORDER BY c.rank DESC
            LIMIT $limit
            """

        return """
        MATCH (c:Community)
        WHERE c.level >= $level
        RETURN c.id AS id,
               c.title AS title,
               c.summary AS summary,
               c.rank AS rank,
               c.entity_count AS entity_count
        ORDER BY c.rank DESC
        LIMIT $limit
        """

    def build_community_entities_query(
        self,
        community_id: str,
        limit: int,
    ) -> str:
        # Validate community_id format
        validate_uuid(community_id, "community_id")
        if limit < 1:
            raise ValueError(f"limit must be positive, got {limit}")

        return """
        MATCH (c:Community {id: $community_id})-[:HAS_ENTITY]->(e:Entity)
        RETURN e.canonical_name AS canonical_name,
               e.type AS type,
               e.description AS description
        LIMIT $limit
        """

    def build_key_entities_query(
        self,
        community_ids: list[str],
        limit: int,
    ) -> str:
        # Validate all community IDs
        for cid in community_ids:
            validate_uuid(cid, "community_id")
        if limit < 1:
            raise ValueError(f"limit must be positive, got {limit}")

        return """
        MATCH (c:Community)-[:HAS_ENTITY]->(e:Entity)
        WHERE c.id IN $community_ids
        WITH e, count(c) AS community_count,
             size((e)-[:RELATED_TO]->()) AS degree
        RETURN e.canonical_name AS canonical_name,
               e.type AS type,
               e.description AS description,
               degree,
               community_count
        ORDER BY community_count DESC, degree DESC
        LIMIT $limit
        """

    def build_communities_exist_query(self, level: int | None) -> str:
        if level is not None:
            # Use >= to find communities at or above the specified level
            return "MATCH (c:Community) WHERE c.level >= $level RETURN count(c) AS count"
        return "MATCH (c:Community) RETURN count(c) AS count"

    def build_vector_search_communities_query(
        self,
        level: int,
        limit: int,
    ) -> str | None:
        if limit < 1:
            raise ValueError(f"limit must be positive, got {limit}")

        return """
        MATCH (r:CommunityReport)-[:REPORTS_ON]->(c:Community)
        WHERE c.level >= $level AND r.full_content_embedding IS NOT NULL
        WITH c, r, vector.similarity.cosine(r.full_content_embedding, $embedding) AS score
        WHERE score > 0.3
        RETURN c.id AS id,
               c.title AS title,
               COALESCE(r.summary, '') AS summary,
               c.rank AS rank,
               c.entity_count AS entity_count,
               r.full_content AS full_content,
               r.key_entities AS key_entities,
               score
        ORDER BY score DESC
        LIMIT $limit
        """

    def build_cross_community_relationships_query(
        self,
        community_ids: list[str],
    ) -> str:
        for cid in community_ids:
            validate_uuid(cid, "community_id")

        # Typed relationships (semantic edge types, excluding generic ones)
        typed_part = """
        MATCH (c1:Community)-[:HAS_ENTITY]->(e1:Entity)
              -[r]->(e2:Entity)<-[:HAS_ENTITY]-(c2:Community)
        WHERE c1.id IN $community_ids
          AND c2.id IN $community_ids
          AND c1.id <> c2.id
          AND NOT type(r) = 'RELATED_TO'
          AND NOT type(r) = 'MENTIONS'
          AND NOT type(r) = 'HAS_ENTITY'
        RETURN DISTINCT
               c1.title AS source_community,
               c2.title AS target_community,
               e1.canonical_name AS source_entity,
               e2.canonical_name AS target_entity,
               type(r) AS relation_type
        LIMIT 50
        """

        # Generic RELATED_TO relationships
        generic_part = """
        MATCH (c1:Community)-[:HAS_ENTITY]->(e1:Entity)
              -[r:RELATED_TO]->(e2:Entity)<-[:HAS_ENTITY]-(c2:Community)
        WHERE c1.id IN $community_ids
          AND c2.id IN $community_ids
          AND c1.id <> c2.id
        RETURN DISTINCT
               c1.title AS source_community,
               c2.title AS target_community,
               e1.canonical_name AS source_entity,
               e2.canonical_name AS target_entity,
               r.relation_type AS relation_type
        LIMIT 50
        """

        return f"{typed_part}\n UNION ALL \n{generic_part}"

    def build_entity_article_fallback_query(
        self,
        tokens: list[str],
        limit: int,
    ) -> str:
        if not tokens:
            raise ValueError("tokens must not be empty")
        if limit < 1:
            raise ValueError(f"limit must be positive, got {limit}")

        return """
        MATCH (a:Article)-[:MENTIONS]->(e:Entity)
        WHERE any(token IN $tokens WHERE
                 toLower(e.canonical_name) CONTAINS token
                 OR toLower(a.title) CONTAINS token
                 OR toLower(a.summary) CONTAINS token)
        RETURN e.canonical_name AS entity_name,
               e.type AS entity_type,
               e.description AS entity_description,
               a.id AS article_id,
               a.title AS article_title,
               a.summary AS article_summary,
               a.score AS article_score,
               size((e)-[:RELATED_TO]->()) AS entity_degree
        ORDER BY article_score DESC, entity_degree DESC
        LIMIT $limit
        """

    def build_entity_article_fallback_with_description_query(
        self,
        tokens: list[str],
        limit: int,
    ) -> str:
        if not tokens:
            raise ValueError("tokens must not be empty")
        if limit < 1:
            raise ValueError(f"limit must be positive, got {limit}")

        # Same as fallback query but also searches entity description
        return """
        MATCH (a:Article)-[:MENTIONS]->(e:Entity)
        WHERE any(token IN $tokens WHERE
                 toLower(e.canonical_name) CONTAINS token
                 OR toLower(e.description) CONTAINS token
                 OR toLower(a.title) CONTAINS token
                 OR toLower(a.summary) CONTAINS token)
        RETURN e.canonical_name AS entity_name,
               e.type AS entity_type,
               e.description AS entity_description,
               a.id AS article_id,
               a.title AS article_title,
               a.summary AS article_summary,
               a.score AS article_score,
               size((e)-[:RELATED_TO]->()) AS entity_degree
        ORDER BY article_score DESC, entity_degree DESC
        LIMIT $limit
        """

    def build_articles_by_text_query(
        self,
        limit: int,
    ) -> str:
        if limit < 1:
            raise ValueError(f"limit must be positive, got {limit}")

        return """
        MATCH (a:Article)
        WHERE toLower(a.title) CONTAINS $query
        RETURN a.id AS id,
               a.title AS title,
               a.summary AS summary,
               a.url AS url,
               a.score AS score
        ORDER BY a.score DESC
        LIMIT $limit
        """


class LadybugQueryBuilder:
    """LadybugDB implementation of GraphQueryBuilder.

    LadybugDB uses a Cypher-like syntax but with some differences:
    - No elementId() function - use id property directly
    - No datetime() function - use string timestamps
    - No list comprehension syntax [n IN list | expr]
    - No DETACH DELETE - must delete relationships manually
    """

    @property
    def database_type(self) -> GraphDatabaseType:
        """Get LadybugDB database type."""
        return GraphDatabaseType.LADYBUG

    # === Capability Detection ===

    def supports_element_id(self) -> bool:
        """LadybugDB doesn't support elementId()."""
        return False

    def supports_datetime_function(self) -> bool:
        """LadybugDB doesn't support datetime(), uses timestamp integers."""
        return False

    def supports_detach_delete(self) -> bool:
        """LadybugDB doesn't support DETACH DELETE."""
        return False

    def supports_list_comprehension(self) -> bool:
        """LadybugDB doesn't support Cypher list comprehension syntax."""
        return False

    # === Expression Builders ===

    def entity_id_expression(self, node_var: str) -> str:
        """LadybugDB uses id property directly."""
        return f"{node_var}.id"

    def weight_expression(self, rel_var: str) -> str:
        """LadybugDB stores weight on RELATED_TO relationship."""
        return f"coalesce({rel_var}.weight, 1.0)"

    # === Metrics Queries ===

    def build_component_neighbors_query(self) -> str:
        """Build LadybugDB component query matching all Entity-to-Entity relationships.

        Uses ``-[r]-`` (LadybugDB does not support ``--`` shorthand) to match
        any relationship type between Entity nodes.
        """
        return """
        MATCH (e:Entity)
        OPTIONAL MATCH (e)-[r]-(connected:Entity)
        WITH e, collect(DISTINCT connected) AS neighbors
        RETURN e.canonical_name AS entity, neighbors, e.type AS type
        """

    def build_degree_query(self) -> str:
        """Build LadybugDB degree query counting all Entity-to-Entity relationships.

        Excludes Article nodes and MENTIONS (counted separately as
        mention_count) so in_degree/out_degree reflect semantic edges only.
        """
        # LadybugDB uses r.edge_type instead of type(r)
        return """
        MATCH (e:Entity)
        OPTIONAL MATCH (e)-[r_out]->(connected_out)
        WHERE NOT connected_out:Article
        OPTIONAL MATCH (connected_in)-[r_in]->(e)
        WHERE NOT connected_in:Article AND r_in.edge_type <> 'MENTIONS'
        OPTIONAL MATCH ()-[m:MENTIONS]->(e)
        WITH e,
             count(DISTINCT r_out) AS out_degree,
             count(DISTINCT r_in) AS in_degree,
             count(DISTINCT m) AS mention_count
        RETURN e.id AS entity_id,
               e.canonical_name AS name,
               e.type AS type,
               out_degree,
               in_degree,
               mention_count,
               (out_degree + in_degree) AS total_degree
        ORDER BY total_degree DESC
        """

    def build_edges_with_weight_query(self) -> str:
        """Build LadybugDB edges query."""
        return """
        MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
        RETURN e1.canonical_name AS source,
               e2.canonical_name AS target,
               coalesce(r.weight, 1.0) AS weight
        """

    # === Entity Repository Queries ===

    def build_get_entity_query(self) -> str:
        """Build LadybugDB query to get entity by canonical name."""
        # LadybugDB Entity schema: id, canonical_name, type, description, tier, created_at, updated_at
        # No aliases property - lookup by canonical_name only
        return """
            MATCH (e:Entity)
            WHERE e.canonical_name = $name
            RETURN e.id as id, e.canonical_name as canonical_name, e.type as type,
                   NULL as aliases, e.description as description,
                   e.updated_at as updated_at
        """

    def build_get_entity_relations_query(self) -> str:
        """Build LadybugDB query to get entity relationships."""
        # LadybugDB Entity has no aliases property
        # LadybugDB stores relationship type as edge_type property
        # Use explicit relationship types in MATCH - exclude MENTIONS
        return """
            MATCH (e:Entity)
            WHERE e.canonical_name = $name
            MATCH (e)-[r:RELATED_TO|CAUSES|ENABLES|PREVENTS|REPORTS_ON|FOLLOWED_BY|EVENT_FOLLOWED_BY|HAS_ENTITY]->(target:Entity)
            RETURN target.canonical_name as target, r.edge_type as relation_type,
                   NULL as source_article_id, r.created_at as created_at
            ORDER BY r.created_at DESC
            LIMIT $limit
        """

    def build_get_related_entities_query(self) -> str:
        """Build LadybugDB query to get entities mentioned in same articles.

        Note: LadybugDB MENTIONS goes FROM Article TO Entity, so we match
        the reverse direction. Returns full entity data including
        description and timestamps.
        """
        # LadybugDB Entity has no aliases property - lookup by canonical_name only
        return """
            MATCH (e:Entity)
            WHERE e.canonical_name = $name
            MATCH (e)-[:MENTIONS]-(a:Article)-[:MENTIONS]-(re:Entity)
            WHERE re.canonical_name <> e.canonical_name
            RETURN re.id as id, re.canonical_name as canonical_name,
                   re.type as type, NULL as aliases,
                   re.description as description,
                   re.created_at as created_at, re.updated_at as updated_at
            LIMIT $limit
        """

    def build_get_entity_articles_query(self) -> str:
        """Build LadybugDB query to get articles mentioning an entity.

        Note: LadybugDB MENTIONS goes FROM Article TO Entity, so we match
        the reverse direction.
        """
        # LadybugDB Entity has no aliases property - lookup by canonical_name only
        return """
            MATCH (e:Entity)
            WHERE e.canonical_name = $name
            MATCH (a:Article)-[:MENTIONS]->(e)
            RETURN a.pg_id as id, a.title as title, a.category as category,
                   a.publish_time as publish_time, a.score as score
            ORDER BY a.publish_time DESC
            LIMIT $limit
        """

    def build_get_article_graph_query(self) -> str:
        """Build LadybugDB query to get article node."""
        return """
            MATCH (a:Article {pg_id: $id})
            RETURN a.pg_id as id, a.title as title, a.category as category,
                   a.publish_time as publish_time, a.score as score
        """

    def build_get_article_entities_query(self) -> str:
        """Build LadybugDB query to get entities mentioned in an article.

        Note: LadybugDB MENTIONS goes FROM Article TO Entity, so we match
        the reverse direction. Returns entity fields including description
        and timestamps for complete entity data.
        """
        return """
            MATCH (a:Article {pg_id: $id})-[r:MENTIONS]->(e:Entity)
            RETURN e.id as id, e.canonical_name as canonical_name, e.type as type,
                   NULL as aliases, e.description as description,
                   e.created_at as created_at, e.updated_at as updated_at,
                   r.role as role
        """

    def build_get_article_relationships_query(self) -> str:
        """Build LadybugDB query to get relationships between entities in an article."""
        # LadybugDB RELATED_TO uses edge_type field, not relation_type
        # No source_article_id in RELATED_TO schema
        return """
            MATCH (a:Article {pg_id: $id})-[:MENTIONS]->(e1:Entity)
            MATCH (e1)-[r:RELATED_TO]->(e2:Entity)
            WHERE (a)-[:MENTIONS]->(e2)
            RETURN e1.canonical_name as source, e2.canonical_name as target,
                   r.edge_type as relation_type,
                   NULL as source_article_id, r.created_at as created_at
        """

    def build_get_related_articles_query(self) -> str:
        """Build LadybugDB query to get related articles.

        Note: LadybugDB doesn't support | syntax for multiple relation types.
        Only FOLLOWED_BY connects Article to Article (MENTIONS is Article->Entity).
        DISTINCT causes "variable not in scope" errors in LadybugDB.
        """
        return """
            MATCH (a:Article {pg_id: $id})-[r:FOLLOWED_BY]->(ra:Article)
            RETURN ra.pg_id as id, ra.title as title, ra.category as category,
                   ra.publish_time as publish_time, ra.score as score
            ORDER BY ra.publish_time DESC
            LIMIT 10
        """

    def build_get_relation_types_query(self, entity_type: str | None = None) -> str:
        """Build LadybugDB query to get relation types for an entity.

        When entity_type is None, matches by canonical_name only — same
        rationale as Neo4j builder.
        """
        # LadybugDB: Use RELATED_TO with edge_type field instead of type(r)
        # Entity has no pruned field in LadybugDB schema
        # Note: LadybugDB doesn't support rebinding relationship in CASE WHEN,
        # so we return 'outgoing' as default primary_direction
        entity_pattern = (
            "{canonical_name: $name, type: $type}"
            if entity_type is not None
            else "{canonical_name: $name}"
        )
        return f"""
            MATCH (e:Entity {entity_pattern})-[r:RELATED_TO]-(other:Entity)
            RETURN r.edge_type AS relation_type,
                   count(DISTINCT other) AS target_count,
                   'outgoing' AS primary_direction
            ORDER BY target_count DESC
        """

    def build_find_by_relation_types_query(
        self, relation_types: list[str] | None, entity_type: str | None = None
    ) -> str:
        """Build LadybugDB query to find entities by relation types."""
        # LadybugDB: Use RELATED_TO with edge_type field
        # Note: LadybugDB doesn't support pattern matching in CASE WHEN,
        # so we return 'outgoing' as default direction
        type_clause = (
            "{canonical_name: $name, type: $type}"
            if entity_type is not None
            else "{canonical_name: $name}"
        )
        if not relation_types:
            return f"""
                MATCH (e:Entity {type_clause})-[r:RELATED_TO]-(other:Entity)
                RETURN r.edge_type AS relation_type,
                       'outgoing' AS direction,
                       other.canonical_name AS target_name,
                       other.type AS target_type,
                       other.description AS target_description,
                       coalesce(r.weight, 1.0) AS weight
                ORDER BY weight DESC
                LIMIT $limit
            """
        else:
            # Filter by specific edge types
            # Validate edge types against whitelist to prevent injection
            validated_types = validate_relation_types(relation_types)
            edge_type_filters = " OR ".join(f"r.edge_type = '{rt}'" for rt in validated_types)
            return f"""
                MATCH (e:Entity {type_clause})-[r:RELATED_TO]-(other:Entity)
                WHERE ({edge_type_filters})
                RETURN r.edge_type AS relation_type,
                       'outgoing' AS direction,
                       other.canonical_name AS target_name,
                       other.type AS target_type,
                       other.description AS target_description,
                       coalesce(r.weight, 1.0) AS weight
                ORDER BY weight DESC
                LIMIT $limit
            """

    # === Visualization Queries ===

    def build_visualization_nodes_query(self) -> str:
        """Build LadybugDB query to get nodes for graph visualization.

        Note: LadybugDB doesn't support list comprehension, so degree is computed
        differently using count on relationship patterns. Degree counts only
        Entity-Entity business relations (excludes MENTIONS/HAS_ENTITY/EVENT_FOLLOWED_BY).
        """
        return """
        MATCH (e:Entity)
        OPTIONAL MATCH (e)-[r]-(other:Entity)
        WHERE NOT r.edge_type IN ['MENTIONS','HAS_ENTITY','EVENT_FOLLOWED_BY']
        WITH e, count(DISTINCT r) AS degree
        RETURN e.canonical_name AS id,
               e.canonical_name AS label,
               e.type AS type,
               e.description AS description,
               degree
        ORDER BY degree DESC
        LIMIT $limit
        """

    def build_visualization_edges_query(self) -> str:
        """Build LadybugDB query to get edges for graph visualization.

        Returns Entity-Entity business relations only. LadybugDB uses
        r.edge_type field for relation type and stores all Entity-Entity
        relations under the RELATED_TO edge table with edge_type discriminator.
        """
        return """
        MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
        WHERE e1.canonical_name IN $node_ids AND e2.canonical_name IN $node_ids
          AND NOT r.edge_type IN ['MENTIONS','HAS_ENTITY','EVENT_FOLLOWED_BY']
        RETURN e1.canonical_name AS source,
               e2.canonical_name AS target,
               r.edge_type AS relation_type,
               r.weight AS weight
        LIMIT $edge_limit
        """

    def build_subgraph_nodes_query(self, hop_pattern: str, include_types: bool) -> str:
        """Build LadybugDB query to get nodes for subgraph extraction.

        Note: LadybugDB supports variable-length path syntax (*1..N).
        """
        if include_types:
            return f"""
            MATCH path = (center:Entity {{canonical_name: $center}})-[r{hop_pattern}]-(related:Entity)
            WHERE related.type IN $include_types
            WITH collect(DISTINCT related) AS related_nodes
            MATCH (center:Entity {{canonical_name: $center}})
            WITH center + related_nodes AS all_nodes
            UNWIND all_nodes AS node
            MATCH (node)-[r]-(other:Entity)
            WHERE other IN all_nodes
            RETURN DISTINCT node.canonical_name AS id,
                   node.canonical_name AS label,
                   node.type AS type,
                   node.description AS description
            LIMIT 200
            """
        else:
            return f"""
            MATCH path = (center:Entity {{canonical_name: $center}})-[r{hop_pattern}]-(related:Entity)
            WITH collect(DISTINCT related) AS related_nodes
            MATCH (center:Entity {{canonical_name: $center}})
            WITH center + related_nodes AS all_nodes
            UNWIND all_nodes AS node
            MATCH (node)-[r]-(other:Entity)
            WHERE other IN all_nodes
            RETURN DISTINCT node.canonical_name AS id,
                   node.canonical_name AS label,
                   node.type AS type,
                   node.description AS description
            LIMIT 200
            """

    def build_subgraph_edges_query(self) -> str:
        """Build LadybugDB query to get edges for subgraph visualization.

        Note: LadybugDB uses r.edge_type for relationship type, not type(r).
        """
        return """
        MATCH (e1:Entity)-[r]->(e2:Entity)
        WHERE e1.canonical_name IN $node_ids AND e2.canonical_name IN $node_ids
        RETURN e1.canonical_name AS source,
               e2.canonical_name AS target,
               r.edge_type AS relation_type,
               r.weight AS weight
        LIMIT 500
        """

    def build_traverse_query(
        self,
        max_depth: int = 3,
        relation_types: list[str] | None = None,
        return_paths: bool = False,
        mode: str = "full",
        min_confidence: float | None = None,
    ) -> str:
        """Build LadybugDB query for multi-hop graph traversal.

        Note: LadybugDB does not support indexing into RECURSIVE_REL lists
        (r[-1] syntax) or type(r) function. Uses a two-step strategy:
        1. Find connected entities via variable-length path matching.
        2. Use OPTIONAL MATCH to get direct relationship between center and
           each connected entity for edge metadata.
        Relationship type filtering (excluding MENTIONS/FOLLOWED_BY) is
        applied on the direct relationship, not the variable-length path.
        """
        confidence_filter = (
            f" AND coalesce(direct_r.weight, 1.0) >= {min_confidence}"
            if min_confidence is not None
            else ""
        )

        if mode == "aggregate":
            return f"""
            MATCH (center:Entity {{canonical_name: $center}})
            MATCH (center)-[r*1..{max_depth}]-(other:Entity)
            WITH count(DISTINCT other) AS total_nodes,
                 count(DISTINCT r) AS total_edges
            RETURN total_nodes, total_edges,
                   '' AS relation_type,
                   0 AS type_count
            """

        return f"""
        MATCH (center:Entity {{canonical_name: $center}})
        MATCH (center)-[r*1..{max_depth}]-(other:Entity)
        WITH DISTINCT other, center
        OPTIONAL MATCH (center)-[direct_r]-(other)
        WHERE direct_r.edge_type <> 'MENTIONS' AND direct_r.edge_type <> 'FOLLOWED_BY'
        {confidence_filter}
        RETURN DISTINCT other.canonical_name AS node_name,
               other.id AS node_id,
               other.type AS node_type,
               other.description AS node_description,
               center.canonical_name AS source,
               other.canonical_name AS target,
               direct_r.edge_type AS relation_type
        LIMIT $limit
        """

    # === Search & Community Query Methods (migrated from graph_query.py) ===

    def build_entity_search_query(self, config: EntitySearchConfig) -> str:
        return """
        MATCH (e:Entity)
        WHERE LOWER(e.canonical_name) CONTAINS $query
        RETURN e.canonical_name AS name
        LIMIT $limit
        """

    def build_entities_by_names_query(self, names: list[str], limit: int) -> str:
        return """
        MATCH (e:Entity)
        WHERE e.canonical_name IN $names
        RETURN e.canonical_name AS canonical_name,
               e.type AS type,
               e.description AS description
        LIMIT $limit
        """

    def build_related_entities_query(self, config: RelatedEntitiesConfig) -> str:
        # Validate max_hops
        if config.max_hops < 1 or config.max_hops > 5:
            raise ValueError(f"max_hops must be between 1 and 5, got {config.max_hops}")

        if config.relation_types:
            # Validate relation types
            for rt in config.relation_types:
                validate_edge_type(rt)
            return f"""
            MATCH (e:Entity)-[r:RELATED_TO*1..{config.max_hops}]-(related:Entity)
            WHERE e.canonical_name IN $names
              AND r.edge_type IN $relation_types
            RETURN DISTINCT related.canonical_name AS canonical_name,
                   related.type AS type,
                   count(e) AS connection_count
            ORDER BY connection_count DESC
            LIMIT $limit
            """

        return f"""
        MATCH (e:Entity)-[r:RELATED_TO*1..{config.max_hops}]-(related:Entity)
        WHERE e.canonical_name IN $names
        RETURN DISTINCT related.canonical_name AS canonical_name,
               related.type AS type,
               count(e) AS connection_count
        ORDER BY connection_count DESC
        LIMIT $limit
        """

    def build_relationships_query(
        self,
        entity_names: list[str],
        relation_types: list[str] | None,
        limit: int,
    ) -> str:
        if relation_types:
            # Validate relation types
            for rt in relation_types:
                validate_edge_type(rt)

            return """
            MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
            WHERE (e1.canonical_name IN $names OR e2.canonical_name IN $names)
              AND r.edge_type IN $relation_types
            RETURN e1.canonical_name AS source_name,
                   e2.canonical_name AS target_name,
                   r.edge_type AS relation_type
            LIMIT $limit
            """

        return """
        MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
        WHERE e1.canonical_name IN $names OR e2.canonical_name IN $names
        RETURN e1.canonical_name AS source_name,
               e2.canonical_name AS target_name,
               r.edge_type AS relation_type
        LIMIT $limit
        """

    def build_articles_by_entities_query(
        self,
        entity_names: list[str],
        limit: int,
    ) -> str:
        return """
        MATCH (a:Article)-[:MENTIONS]->(e:Entity)
        WHERE e.canonical_name IN $names
        RETURN DISTINCT a.pg_id AS id,
               a.title AS title,
               a.summary AS summary,
               a.publish_time AS publish_time
        ORDER BY a.publish_time DESC
        LIMIT $limit
        """

    def build_community_search_query(
        self,
        config: CommunitySearchConfig,
    ) -> str:
        limit = config.limit or 10
        if limit < 1:
            raise ValueError(f"limit must be positive, got {limit}")

        if config.query:
            return """
            MATCH (c:Community)
            WHERE c.level >= $level
              AND (LOWER(c.title) CONTAINS $query
                   OR LOWER(c.summary) CONTAINS $query)
            RETURN c.id AS id,
                   c.title AS title,
                   c.summary AS summary,
                   c.rank AS rank
            ORDER BY c.rank DESC
            LIMIT $limit
            """

        return """
        MATCH (c:Community)
        WHERE c.level >= $level
        RETURN c.id AS id,
               c.title AS title,
               c.summary AS summary,
               c.rank AS rank
        ORDER BY c.rank DESC
        LIMIT $limit
        """

    def build_community_entities_query(
        self,
        community_id: str,
        limit: int,
    ) -> str:
        # Validate community_id format
        validate_uuid(community_id, "community_id")
        if limit < 1:
            raise ValueError(f"limit must be positive, got {limit}")

        return """
        MATCH (c:Community {id: $community_id})-[:HAS_ENTITY]->(e:Entity)
        RETURN e.canonical_name AS canonical_name,
               e.type AS type,
               e.description AS description
        LIMIT $limit
        """

    def build_key_entities_query(
        self,
        community_ids: list[str],
        limit: int,
    ) -> str:
        # Validate all community IDs
        for cid in community_ids:
            validate_uuid(cid, "community_id")
        if limit < 1:
            raise ValueError(f"limit must be positive, got {limit}")

        return """
        MATCH (c:Community)-[:HAS_ENTITY]->(e:Entity)
        WHERE c.id IN $community_ids
        WITH e, count(c) AS community_count
        RETURN e.canonical_name AS canonical_name,
               e.type AS type,
               e.description AS description,
               community_count
        ORDER BY community_count DESC
        LIMIT $limit
        """

    def build_communities_exist_query(self, level: int | None) -> str:
        if level is not None:
            # Use >= to find communities at or above the specified level
            return "MATCH (c:Community) WHERE c.level >= $level RETURN count(c) AS count"
        return "MATCH (c:Community) RETURN count(c) AS count"

    def build_vector_search_communities_query(
        self,
        level: int,
        limit: int,
    ) -> str | None:
        """LadybugDB doesn't support native vector search.

        Returns None to indicate vector search is not available.
        The caller should fall back to text search.
        """
        return None

    def build_cross_community_relationships_query(
        self,
        community_ids: list[str],
    ) -> str:
        for cid in community_ids:
            validate_uuid(cid, "community_id")

        return """
        MATCH (c1:Community)-[:HAS_ENTITY]->(e1:Entity)
              -[r:RELATED_TO]->(e2:Entity)<-[:HAS_ENTITY]-(c2:Community)
        WHERE c1.id IN $community_ids
          AND c2.id IN $community_ids
          AND c1.id <> c2.id
        RETURN DISTINCT
               c1.title AS source_community,
               c2.title AS target_community,
               e1.canonical_name AS source_entity,
               e2.canonical_name AS target_entity,
               r.edge_type AS relation_type
        LIMIT 50
        """

    def build_entity_article_fallback_query(
        self,
        tokens: list[str],
        limit: int,
    ) -> str:
        if not tokens:
            raise ValueError("tokens must not be empty")
        if limit < 1:
            raise ValueError(f"limit must be positive, got {limit}")

        # LadybugDB searches Entity directly (MENTIONS edges may not exist)
        return """
        MATCH (e:Entity)
        WHERE any(token IN $tokens WHERE
                 e.canonical_name CONTAINS token)
        RETURN e.canonical_name AS entity_name,
               e.type AS entity_type,
               e.description AS entity_description,
               e.tier AS entity_tier
        ORDER BY e.tier ASC
        LIMIT $limit
        """

    def build_entity_article_fallback_with_description_query(
        self,
        tokens: list[str],
        limit: int,
    ) -> str:
        if not tokens:
            raise ValueError("tokens must not be empty")
        if limit < 1:
            raise ValueError(f"limit must be positive, got {limit}")

        # LadybugDB: also search description field for Chinese queries
        return """
        MATCH (e:Entity)
        WHERE any(token IN $tokens WHERE
                 e.canonical_name CONTAINS token
                 OR e.description CONTAINS token)
        RETURN e.canonical_name AS entity_name,
               e.type AS entity_type,
               e.description AS entity_description,
               e.tier AS entity_tier
        ORDER BY e.tier ASC
        LIMIT $limit
        """

    def build_articles_by_text_query(
        self,
        limit: int,
    ) -> str:
        if limit < 1:
            raise ValueError(f"limit must be positive, got {limit}")

        # LadybugDB: Article may not have summary/url, use title only
        return """
        MATCH (a:Article)
        WHERE LOWER(a.title) CONTAINS LOWER($query)
        RETURN a.title AS title
        LIMIT $limit
        """


def create_graph_query_builder(db_type: str | GraphDatabaseType) -> GraphQueryBuilder:
    """Create appropriate query builder for graph database type.

    Args:
        db_type: Database type string or enum value ('neo4j' or 'ladybug').

    Returns:
        Database-specific GraphQueryBuilder implementation.

    Raises:
        ValueError: If database type is not supported.
    """
    if isinstance(db_type, str):
        try:
            db_type = GraphDatabaseType(db_type.lower())
        except ValueError:
            supported = ", ".join(t.value for t in GraphDatabaseType)
            raise ValueError(
                f"Unsupported graph database type: {db_type} (supported: {supported})"
            ) from None

    if db_type == GraphDatabaseType.NEO4J:
        return Neo4jQueryBuilder()
    elif db_type == GraphDatabaseType.LADYBUG:
        return LadybugQueryBuilder()
    else:
        supported = ", ".join(t.value for t in GraphDatabaseType)
        raise ValueError(f"Unsupported graph database type: {db_type} (supported: {supported})")
