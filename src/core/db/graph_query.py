# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Graph database query builders for entity and community operations.

This module provides a QueryBuilder pattern to abstract database-specific
syntax differences between Neo4j Cypher and LadybugDB SQL variant for
graph traversal operations.

IMPORTANT: All queries use parameterized syntax ($param) to prevent injection.
For cases where parameters cannot be used (e.g., dynamic relation types),
input validation is performed via safe_query module.

Usage:
    from core.db.graph_query import create_graph_query_builder

    builder = create_graph_query_builder("neo4j")
    query = builder.build_entity_search_query(query="test", limit=10)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from core.db.safe_query import (
    validate_edge_type,
    validate_uuid,
)


class GraphDatabaseType(str, Enum):
    """Supported graph database types."""

    NEO4J = "neo4j"
    LADYBUG = "ladybug"


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


class GraphQueryBuilder(ABC):
    """Abstract base class for database-specific graph query builders.

    Implementations provide database-specific query syntax for:
    - Entity search and retrieval
    - Relationship traversal
    - Community queries
    - Temporal event queries

    All implementations MUST use parameterized queries where possible.
    """

    @property
    @abstractmethod
    def database_type(self) -> GraphDatabaseType:
        """Return the database type this builder supports."""
        ...

    @abstractmethod
    def build_entity_search_query(self, config: EntitySearchConfig) -> str:
        """Build query to find entities by name/alias search.

        Args:
            config: Search configuration.

        Returns:
            Query string with $query and $limit parameters.
        """
        ...

    @abstractmethod
    def build_entities_by_names_query(self, names: list[str], limit: int) -> str:
        """Build query to get entities by canonical names.

        Args:
            names: List of entity names to fetch.
            limit: Maximum results.

        Returns:
            Query string with $names parameter.
        """
        ...

    @abstractmethod
    def build_related_entities_query(self, config: RelatedEntitiesConfig) -> str:
        """Build query to get entities related to source entities.

        Args:
            config: Related entities configuration.

        Returns:
            Query string with $names and $limit parameters.
        """
        ...

    @abstractmethod
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

    @abstractmethod
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

    @abstractmethod
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

    @abstractmethod
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

    @abstractmethod
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

    @abstractmethod
    def build_communities_exist_query(self, level: int | None) -> str:
        """Build query to check if communities exist.

        Args:
            level: Optional level filter.

        Returns:
            Query string returning count.
        """
        ...

    @abstractmethod
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

    @abstractmethod
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

    @abstractmethod
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

    @abstractmethod
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

    @abstractmethod
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


class Neo4jQueryBuilder(GraphQueryBuilder):
    """Query builder for Neo4j using Cypher syntax.

    All queries use parameterized syntax ($param) for safe query construction.
    """

    @property
    def database_type(self) -> GraphDatabaseType:
        return GraphDatabaseType.NEO4J

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


class LadybugQueryBuilder(GraphQueryBuilder):
    """Query builder for LadybugDB using SQL-like syntax.

    LadybugDB supports a subset of Cypher with some differences:
    - Uses SQL-like syntax for some operations
    - TYPE() function not supported - use edge_type property
    - Limited support for some Cypher functions

    All queries use parameterized syntax where supported.
    For IN clauses, parameters are used with list values.
    """

    @property
    def database_type(self) -> GraphDatabaseType:
        return GraphDatabaseType.LADYBUG

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


def create_graph_query_builder(
    database_type: GraphDatabaseType | str,
) -> GraphQueryBuilder:
    """Factory function to create the appropriate graph query builder.

    Args:
        database_type: Database type enum value or string ('neo4j' or 'ladybug').

    Returns:
        GraphQueryBuilder implementation for the specified database.

    Raises:
        ValueError: If database_type is not supported.
    """
    if isinstance(database_type, str):
        try:
            database_type = GraphDatabaseType(database_type.lower())
        except ValueError:
            raise ValueError(
                f"Unsupported graph database type: {database_type}. "
                f"Supported types: {[t.value for t in GraphDatabaseType]}"
            ) from None

    builders: dict[GraphDatabaseType, type[GraphQueryBuilder]] = {
        GraphDatabaseType.NEO4J: Neo4jQueryBuilder,
        GraphDatabaseType.LADYBUG: LadybugQueryBuilder,
    }

    builder_class = builders.get(database_type)
    if builder_class is None:
        raise ValueError(f"No builder registered for database type: {database_type}")

    return builder_class()


__all__ = [
    "CommunitySearchConfig",
    "EntitySearchConfig",
    "GraphDatabaseType",
    "GraphQueryBuilder",
    "LadybugQueryBuilder",
    "Neo4jQueryBuilder",
    "RelatedEntitiesConfig",
    "create_graph_query_builder",
]
