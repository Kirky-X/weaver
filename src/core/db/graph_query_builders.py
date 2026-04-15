# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Database-agnostic query builders for graph database operations.

Provides a QueryBuilder pattern that abstracts database-specific graph query syntax,
supporting both Neo4j (Cypher) and LadybugDB backends.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable


class GraphDatabaseType(str, Enum):
    """Supported graph database types."""

    NEO4J = "neo4j"
    LADYBUG = "ladybug"


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

    def build_get_relation_types_query(self) -> str:
        """Build query to get relation types for an entity."""
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
        """Build Neo4j component query with list comprehension."""
        return """
        MATCH (e:Entity)
        OPTIONAL MATCH (e)-[:RELATED_TO]-(connected:Entity)
        WITH e, collect(DISTINCT connected) AS neighbors
        RETURN e.canonical_name AS entity,
               [n IN neighbors | n.canonical_name] AS neighbors,
               e.type AS type
        """

    def build_degree_query(self) -> str:
        """Build Neo4j degree query."""
        return """
        MATCH (e:Entity)
        OPTIONAL MATCH (e)-[r_out:RELATED_TO]->()
        OPTIONAL MATCH ()-[r_in:RELATED_TO]->(e)
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
        """Build Neo4j query to get articles mentioning an entity."""
        # Support lookup by canonical_name OR alias
        return """
            MATCH (e:Entity)
            WHERE e.canonical_name = $name OR $name IN e.aliases
            MATCH (e)-[:MENTIONS]->(a:Article)
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
                   e.aliases as aliases, r.role as role
        """

    def build_get_article_relationships_query(self) -> str:
        """Build Neo4j query to get relationships between entities in an article."""
        return """
            MATCH (a:Article {pg_id: $id})-[:MENTIONS]->(e1:Entity)
            MATCH (e1)-[r:RELATED_TO]->(e2:Entity)
            WHERE (a)-[:MENTIONS]->(e2)
            RETURN e1.canonical_name as source, e2.canonical_name as target,
                   r.relation_type as relation_type,
                   r.source_article_id as source_article_id, r.created_at as created_at
        """

    def build_get_related_articles_query(self) -> str:
        """Build Neo4j query to get related articles."""
        return """
            MATCH (a:Article {pg_id: $id})-[r:FOLLOWED_BY|MENTIONS]->(ra:Article)
            RETURN DISTINCT ra.pg_id as id, ra.title as title, ra.category as category,
                   ra.publish_time as publish_time, ra.score as score,
                   type(r) as relation_type
            ORDER BY ra.publish_time DESC
            LIMIT 10
        """

    def build_get_relation_types_query(self) -> str:
        """Build Neo4j query to get relation types for an entity."""
        return """
            MATCH (e:Entity {canonical_name: $name, type: $type})-[r]-(other:Entity)
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
        """Build Neo4j query to get nodes for graph visualization."""
        return """
        MATCH (e:Entity)
        RETURN e.canonical_name AS id,
               e.canonical_name AS label,
               e.type AS type,
               e.description AS description,
               size([(e)-[:RELATED_TO]-()|1]) AS degree
        ORDER BY degree DESC
        LIMIT $limit
        """

    def build_visualization_edges_query(self) -> str:
        """Build Neo4j query to get edges for graph visualization."""
        return """
        MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
        WHERE e1.canonical_name IN $node_ids AND e2.canonical_name IN $node_ids
        RETURN e1.canonical_name AS source,
               e2.canonical_name AS target,
               r.relation_type AS relation_type,
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
        """Build LadybugDB component query without list comprehension.

        Returns neighbors as a list of Entity nodes, which must be processed
        in Python to extract canonical_name values.
        """
        return """
        MATCH (e:Entity)
        OPTIONAL MATCH (e)-[:RELATED_TO]-(connected:Entity)
        WITH e, collect(DISTINCT connected) AS neighbors
        RETURN e.canonical_name AS entity, neighbors, e.type AS type
        """

    def build_degree_query(self) -> str:
        """Build LadybugDB degree query using id property."""
        return """
        MATCH (e:Entity)
        OPTIONAL MATCH (e)-[r_out:RELATED_TO]->()
        OPTIONAL MATCH ()-[r_in:RELATED_TO]->(e)
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
        """Build LadybugDB query to get entity by canonical name or alias."""
        # Support lookup by canonical_name OR alias
        # LadybugDB uses array_contains for LIST type
        return """
            MATCH (e:Entity)
            WHERE e.canonical_name = $name OR array_contains(e.aliases, $name)
            RETURN e.id as id, e.canonical_name as canonical_name, e.type as type,
                   e.aliases as aliases, e.description as description,
                   e.updated_at as updated_at
        """

    def build_get_entity_relations_query(self) -> str:
        """Build LadybugDB query to get entity relationships."""
        # Support lookup by canonical_name OR alias
        # Use untyped pattern -[r]-> to match all semantic relationships
        # LadybugDB stores relationship type as edge_type property
        # Exclude MENTIONS (metadata relation, not domain semantics)
        return """
            MATCH (e:Entity)
            WHERE e.canonical_name = $name OR array_contains(e.aliases, $name)
            MATCH (e)-[r]->(target:Entity)
            WHERE type(r) <> 'MENTIONS'
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
        # Support lookup by canonical_name OR alias
        return """
            MATCH (e:Entity)
            WHERE e.canonical_name = $name OR array_contains(e.aliases, $name)
            MATCH (e)-[:MENTIONS]-(a:Article)-[:MENTIONS]-(re:Entity)
            WHERE re.canonical_name <> e.canonical_name
            RETURN re.id as id, re.canonical_name as canonical_name,
                   re.type as type, re.aliases as aliases,
                   re.description as description,
                   re.created_at as created_at, re.updated_at as updated_at
            LIMIT $limit
        """

    def build_get_entity_articles_query(self) -> str:
        """Build LadybugDB query to get articles mentioning an entity.

        Note: LadybugDB MENTIONS goes FROM Article TO Entity, so we match
        the reverse direction.
        """
        # Support lookup by canonical_name OR alias
        return """
            MATCH (e:Entity)
            WHERE e.canonical_name = $name OR array_contains(e.aliases, $name)
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

    def build_get_relation_types_query(self) -> str:
        """Build LadybugDB query to get relation types for an entity."""
        # LadybugDB: Use RELATED_TO with edge_type field instead of type(r)
        # Entity has no pruned field in LadybugDB schema
        # Note: LadybugDB doesn't support rebinding relationship in CASE WHEN,
        # so we return 'outgoing' as default primary_direction
        return """
            MATCH (e:Entity {canonical_name: $name, type: $type})-[r:RELATED_TO]-(other:Entity)
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
        differently using count on relationship patterns.
        """
        return """
        MATCH (e:Entity)
        OPTIONAL MATCH (e)-[r:RELATED_TO]-()
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

        Note: LadybugDB RELATED_TO uses edge_type field, not relation_type.
        """
        return """
        MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
        WHERE e1.canonical_name IN $node_ids AND e2.canonical_name IN $node_ids
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

        Note: LadybugDB RELATED_TO uses edge_type field, not relation_type.
        """
        return """
        MATCH (e1:Entity)-[r]->(e2:Entity)
        WHERE e1.canonical_name IN $node_ids AND e2.canonical_name IN $node_ids
        RETURN e1.canonical_name AS source,
               e2.canonical_name AS target,
               type(r) AS relation_type,
               r.weight AS weight
        LIMIT 500
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
            raise ValueError(f"Unsupported graph database type: {db_type}") from None

    if db_type == GraphDatabaseType.NEO4J:
        return Neo4jQueryBuilder()
    elif db_type == GraphDatabaseType.LADYBUG:
        return LadybugQueryBuilder()
    else:
        raise ValueError(f"Unsupported graph database type: {db_type}")
