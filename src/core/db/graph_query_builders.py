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

    def build_find_by_relation_types_query(self, relation_types: list[str] | None) -> str:
        """Build query to find entities by relation types."""
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
        """Build Neo4j query to get entity by canonical name and type."""
        return """
            MATCH (e:Entity {canonical_name: $name})
            RETURN e.id as id, e.canonical_name as canonical_name, e.type as type,
                   e.aliases as aliases, e.description as description,
                   e.updated_at as updated_at
        """

    def build_get_entity_relations_query(self) -> str:
        """Build Neo4j query to get entity relationships."""
        return """
            MATCH (e:Entity {canonical_name: $name})-[r:RELATED_TO]->(target:Entity)
            RETURN target.canonical_name as target, r.relation_type as relation_type,
                   r.source_article_id as source_article_id, r.created_at as created_at
            ORDER BY r.created_at DESC
            LIMIT $limit
        """

    def build_get_related_entities_query(self) -> str:
        """Build Neo4j query to get entities mentioned in same articles."""
        return """
            MATCH (e:Entity {canonical_name: $name})-[:MENTIONS]-(a:Article)-[:MENTIONS]-(re:Entity)
            WHERE re.canonical_name <> $name
            RETURN DISTINCT re.id as id, re.canonical_name as canonical_name,
                   re.type as type, re.aliases as aliases
            LIMIT $limit
        """

    def build_get_entity_articles_query(self) -> str:
        """Build Neo4j query to get articles mentioning an entity."""
        return """
            MATCH (e:Entity {canonical_name: $name})-[:MENTIONS]->(a:Article)
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
              AND NOT other.pruned = true
            RETURN type(r) AS relation_type,
                   count(DISTINCT other) AS target_count,
                   head(collect(DISTINCT
                       CASE WHEN (e)-[r]->(other) THEN 'outgoing' ELSE 'incoming' END
                   )) AS primary_direction
            ORDER BY target_count DESC
        """

    def build_find_by_relation_types_query(self, relation_types: list[str] | None) -> str:
        """Build Neo4j query to find entities by relation types."""
        if not relation_types:
            return """
                MATCH (e:Entity {canonical_name: $name, type: $type})-[r]-(other:Entity)
                WHERE type(r) <> 'MENTIONS' AND type(r) <> 'FOLLOWED_BY'
                  AND NOT other.pruned = true
                RETURN type(r) AS relation_type,
                       CASE WHEN (e)-[r]->(other) THEN 'outgoing' ELSE 'incoming' END AS direction,
                       other.canonical_name AS target_name,
                       other.type AS target_type,
                       other.description AS target_description,
                       coalesce(r.weight, 1.0) AS weight
                ORDER BY weight DESC
                LIMIT $limit
            """
        else:
            type_filters = " OR ".join(f"type(r) = '{rt}'" for rt in relation_types)
            return f"""
                MATCH (e:Entity {{canonical_name: $name, type: $type}})-[r]-(other:Entity)
                WHERE ({type_filters})
                  AND type(r) <> 'MENTIONS' AND type(r) <> 'FOLLOWED_BY'
                  AND NOT other.pruned = true
                RETURN type(r) AS relation_type,
                       CASE WHEN (e)-[r]->(other) THEN 'outgoing' ELSE 'incoming' END AS direction,
                       other.canonical_name AS target_name,
                       other.type AS target_type,
                       other.description AS target_description,
                       coalesce(r.weight, 1.0) AS weight
                ORDER BY weight DESC
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
        """Build LadybugDB query to get entity by canonical name and type."""
        return """
            MATCH (e:Entity {canonical_name: $name})
            RETURN e.id as id, e.canonical_name as canonical_name, e.type as type,
                   e.aliases as aliases, e.description as description,
                   e.updated_at as updated_at
        """

    def build_get_entity_relations_query(self) -> str:
        """Build LadybugDB query to get entity relationships."""
        return """
            MATCH (e:Entity {canonical_name: $name})-[r:RELATED_TO]->(target:Entity)
            RETURN target.canonical_name as target, r.relation_type as relation_type,
                   r.source_article_id as source_article_id, r.created_at as created_at
            ORDER BY r.created_at DESC
            LIMIT $limit
        """

    def build_get_related_entities_query(self) -> str:
        """Build LadybugDB query to get entities mentioned in same articles."""
        return """
            MATCH (e:Entity {canonical_name: $name})-[:MENTIONS]-(a:Article)-[:MENTIONS]-(re:Entity)
            WHERE re.canonical_name <> $name
            RETURN DISTINCT re.id as id, re.canonical_name as canonical_name,
                   re.type as type, re.aliases as aliases
            LIMIT $limit
        """

    def build_get_entity_articles_query(self) -> str:
        """Build LadybugDB query to get articles mentioning an entity."""
        return """
            MATCH (e:Entity {canonical_name: $name})-[:MENTIONS]->(a:Article)
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
        """Build LadybugDB query to get entities mentioned in an article."""
        return """
            MATCH (a:Article {pg_id: $id})-[r:MENTIONS]->(e:Entity)
            RETURN e.id as id, e.canonical_name as canonical_name, e.type as type,
                   e.aliases as aliases, r.role as role
        """

    def build_get_article_relationships_query(self) -> str:
        """Build LadybugDB query to get relationships between entities in an article."""
        return """
            MATCH (a:Article {pg_id: $id})-[:MENTIONS]->(e1:Entity)
            MATCH (e1)-[r:RELATED_TO]->(e2:Entity)
            WHERE (a)-[:MENTIONS]->(e2)
            RETURN e1.canonical_name as source, e2.canonical_name as target,
                   r.relation_type as relation_type,
                   r.source_article_id as source_article_id, r.created_at as created_at
        """

    def build_get_related_articles_query(self) -> str:
        """Build LadybugDB query to get related articles."""
        return """
            MATCH (a:Article {pg_id: $id})-[r:FOLLOWED_BY|MENTIONS]->(ra:Article)
            RETURN DISTINCT ra.pg_id as id, ra.title as title, ra.category as category,
                   ra.publish_time as publish_time, ra.score as score
            ORDER BY ra.publish_time DESC
            LIMIT 10
        """

    def build_get_relation_types_query(self) -> str:
        """Build LadybugDB query to get relation types for an entity."""
        return """
            MATCH (e:Entity {canonical_name: $name, type: $type})-[r]-(other:Entity)
            WHERE type(r) <> 'MENTIONS' AND type(r) <> 'FOLLOWED_BY'
              AND NOT other.pruned = true
            RETURN type(r) AS relation_type,
                   count(DISTINCT other) AS target_count,
                   head(collect(DISTINCT
                       CASE WHEN (e)-[r]->(other) THEN 'outgoing' ELSE 'incoming' END
                   )) AS primary_direction
            ORDER BY target_count DESC
        """

    def build_find_by_relation_types_query(self, relation_types: list[str] | None) -> str:
        """Build LadybugDB query to find entities by relation types."""
        if not relation_types:
            return """
                MATCH (e:Entity {canonical_name: $name, type: $type})-[r]-(other:Entity)
                WHERE type(r) <> 'MENTIONS' AND type(r) <> 'FOLLOWED_BY'
                  AND NOT other.pruned = true
                RETURN type(r) AS relation_type,
                       CASE WHEN (e)-[r]->(other) THEN 'outgoing' ELSE 'incoming' END AS direction,
                       other.canonical_name AS target_name,
                       other.type AS target_type,
                       other.description AS target_description,
                       coalesce(r.weight, 1.0) AS weight
                ORDER BY weight DESC
                LIMIT $limit
            """
        else:
            type_filters = " OR ".join(f"type(r) = '{rt}'" for rt in relation_types)
            return f"""
                MATCH (e:Entity {{canonical_name: $name, type: $type}})-[r]-(other:Entity)
                WHERE ({type_filters})
                  AND type(r) <> 'MENTIONS' AND type(r) <> 'FOLLOWED_BY'
                  AND NOT other.pruned = true
                RETURN type(r) AS relation_type,
                       CASE WHEN (e)-[r]->(other) THEN 'outgoing' ELSE 'incoming' END AS direction,
                       other.canonical_name AS target_name,
                       other.type AS target_type,
                       other.description AS target_description,
                       coalesce(r.weight, 1.0) AS weight
                ORDER BY weight DESC
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
            raise ValueError(f"Unsupported graph database type: {db_type}") from None

    if db_type == GraphDatabaseType.NEO4J:
        return Neo4jQueryBuilder()
    elif db_type == GraphDatabaseType.LADYBUG:
        return LadybugQueryBuilder()
    else:
        raise ValueError(f"Unsupported graph database type: {db_type}")
