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
    - Different parameter binding syntax
    """

    @property
    def database_type(self) -> GraphDatabaseType:
        """Get LadybugDB database type."""
        return GraphDatabaseType.LADYBUG

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
