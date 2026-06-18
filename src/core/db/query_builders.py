# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Database-agnostic query builders for vector similarity operations.

Provides a QueryBuilder pattern that abstracts database-specific SQL syntax
for vector operations, supporting both PostgreSQL (pgvector) and DuckDB backends.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from core.db.models import VectorType

if TYPE_CHECKING:
    pass


class DatabaseType(str, Enum):
    """Supported database types for vector operations."""

    POSTGRES = "postgres"
    DUCKDB = "duckdb"


# Re-exported from safe_query for backward compatibility:
# - validate_sql_identifier (canonical: core.db.safe_query)
# Re-exported from models for backward compatibility:
# - VectorType (canonical: core.db.models)


def validate_limit(limit: int) -> int:
    """Validate limit is within safe bounds.

    Args:
        limit: Limit value to validate.

    Returns:
        The validated limit.

    Raises:
        ValueError: If limit is out of bounds.
    """
    if not 1 <= limit <= 1000:
        raise ValueError(f"Invalid limit: {limit}, must be 1-1000")
    return limit


def validate_threshold(threshold: float) -> float:
    """Validate threshold is within valid range.

    Args:
        threshold: Threshold value to validate.

    Returns:
        The validated threshold.

    Raises:
        ValueError: If threshold is out of range.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"Invalid threshold: {threshold}, must be 0.0-1.0")
    return threshold


@dataclass(frozen=True)
class SimilarityQuery:
    """Configuration for similarity search queries.

    Attributes:
        embedding_param: Parameter name for embedding vector.
        threshold: Minimum cosine similarity threshold (0.0 to 1.0).
        limit: Maximum number of results to return.
        category_param: Parameter name for category filter.
        model_id_param: Parameter name for model ID filter.
        vector_type: Type of vector ('content' or 'title').
        filter_by_category: Whether to filter by category.
        filter_by_model_id: Whether to filter by model_id.
    """

    embedding_param: str = ":embedding"
    threshold: float = 0.80
    limit: int = 20
    category_param: str = ":category"
    model_id_param: str = ":model_id"
    vector_type: str = "content"
    filter_by_category: bool = False
    filter_by_model_id: bool = False


@dataclass(frozen=True)
class EntitySimilarityQuery:
    """Configuration for entity similarity search queries.

    Attributes:
        embedding_param: Parameter name for embedding vector.
        threshold: Minimum cosine similarity threshold (0.0 to 1.0).
        limit: Maximum number of results to return.
    """

    embedding_param: str = ":embedding"
    threshold: float = 0.85
    limit: int = 5


@runtime_checkable
class VectorQueryBuilder(Protocol):
    """Protocol for database-specific vector query builders.

    Defines the interface for building database-agnostic vector operations.
    Implementations must handle database-specific SQL syntax differences.
    """

    @property
    def database_type(self) -> DatabaseType:
        """Get the database type for this builder."""
        ...

    def get_session_init_statements(self) -> list[str]:
        """Get database-specific session initialization statements.

        Returns:
            List of SQL statements to execute at session start.
        """
        ...

    def format_embedding_param(self, embedding: list[float]) -> str | list[float]:
        """Format embedding vector for SQL parameter binding.

        Args:
            embedding: Vector of floats.

        Returns:
            Database-specific formatted value for embedding parameter.
        """
        ...

    def build_similarity_expression(self, column: str) -> str:
        """Build similarity expression for ordering.

        Args:
            column: Name of the embedding column.

        Returns:
            SQL expression for similarity calculation.
        """
        ...

    def build_vector_cast(self, param: str) -> str:
        """Build vector cast expression.

        Args:
            param: Parameter placeholder.

        Returns:
            SQL expression for casting parameter to vector type.
        """
        ...

    def build_upsert_article_vector_query(self) -> str:
        """Build upsert query for article vectors.

        Returns:
            SQL query string for upserting article vectors.
        """
        ...

    def build_upsert_article_vector_batch_query(self, batch_size: int) -> str:
        """Build batch upsert query for multiple article vectors.

        Args:
            batch_size: Number of vectors in the batch.

        Returns:
            SQL query string with placeholders for batch_size vectors.
        """
        ...

    def build_find_similar_articles_query(self, config: SimilarityQuery) -> str:
        """Build similarity search query for articles.

        Args:
            config: Query configuration with threshold and limit.

        Returns:
            SQL query string for finding similar articles.
        """
        ...

    def build_find_similar_entities_query(self, config: EntitySimilarityQuery) -> str:
        """Build similarity search query for entities.

        Args:
            config: Query configuration with threshold and limit.

        Returns:
            SQL query string for finding similar entities.
        """
        ...

    def build_array_contains_expression(self, column: str, param: str) -> str:
        """Build array contains expression for filtering.

        Args:
            column: Column name to check.
            param: Parameter placeholder.

        Returns:
            Database-specific SQL expression for array containment.
        """
        ...


class PgVectorQueryBuilder:
    """PostgreSQL (pgvector) implementation of VectorQueryBuilder."""

    @property
    def database_type(self) -> DatabaseType:
        """Get PostgreSQL database type."""
        return DatabaseType.POSTGRES

    def get_session_init_statements(self) -> list[str]:
        """No static HNSW init — ef_search is set dynamically per query.

        Dynamic ef_search is managed by EfSearchManager based on search mode.
        See: src/modules/knowledge/search/ef_search_manager.py
        """
        return []

    def format_embedding_param(self, embedding: list[float]) -> str:
        """Format as pgvector array literal."""
        return f"[{','.join(str(x) for x in embedding)}]"

    def build_similarity_expression(self, column: str) -> str:
        """Build pgvector cosine distance expression."""
        return f"1 - ({column} <=> cast(:embedding as vector))"

    def build_vector_cast(self, param: str) -> str:
        """Build PostgreSQL vector cast."""
        return f"cast({param} as vector)"

    def build_upsert_article_vector_query(self) -> str:
        """Build PostgreSQL upsert with ON CONFLICT."""
        return """
               INSERT INTO article_vectors (article_id, vector_type, embedding, model_id)
               VALUES (:article_id, :vector_type, CAST(:embedding AS vector), :model_id) ON CONFLICT (article_id, vector_type)
            DO
               UPDATE SET embedding = EXCLUDED.embedding, model_id = EXCLUDED.model_id, updated_at = NOW() \
               """

    def build_upsert_article_vector_batch_query(self, batch_size: int) -> str:
        """Build PostgreSQL batch upsert with ON CONFLICT."""
        values_placeholders = ", ".join(
            f"(:article_id_{i}, :vector_type_{i}, CAST(:embedding_{i} AS vector), :model_id_{i})"
            for i in range(batch_size)
        )
        return f"""
            INSERT INTO article_vectors (article_id, vector_type, embedding, model_id)
            VALUES {values_placeholders}
            ON CONFLICT (article_id, vector_type)
            DO UPDATE SET embedding = EXCLUDED.embedding, model_id = EXCLUDED.model_id, updated_at = NOW()
        """

    def build_find_similar_articles_query(self, config: SimilarityQuery) -> str:
        """Build pgvector cosine similarity search."""
        # Validate inputs for security
        validate_limit(config.limit)
        validate_threshold(config.threshold)
        VectorType(config.vector_type)  # Validate against enum

        similarity_expr = self.build_similarity_expression("av.embedding")

        # Build WHERE conditions based on filter flags
        conditions = ["av.vector_type = :vector_type"]

        if config.filter_by_category:
            conditions.append(f"a.category = {config.category_param}")

        if config.filter_by_model_id:
            conditions.append(f"av.model_id = {config.model_id_param}")

        conditions.append(f"{similarity_expr} >= :threshold")

        where_clause = " AND ".join(conditions)

        return f"""
            SELECT
                a.id::text AS article_id,
                a.category,
                {similarity_expr} AS similarity,
                a.publish_time,
                a.created_at
            FROM article_vectors av
            JOIN articles a ON a.id = av.article_id
            WHERE {where_clause}
            ORDER BY similarity DESC
            LIMIT {config.limit}
        """

    def build_find_similar_entities_query(self, config: EntitySimilarityQuery) -> str:
        """Build pgvector entity similarity search."""
        # Validate inputs for security
        validate_limit(config.limit)
        validate_threshold(config.threshold)

        similarity_expr = self.build_similarity_expression("embedding")
        return f"""
            SELECT
                neo4j_id,
                {similarity_expr} AS similarity
            FROM entity_vectors
            WHERE {similarity_expr} >= {config.threshold}
            ORDER BY similarity DESC
            LIMIT {config.limit}
        """

    def build_array_contains_expression(self, column: str, param: str) -> str:
        """PostgreSQL ANY expression for array containment."""
        return f"{column} = ANY({param})"

    def build_upsert_entity_vector_query(self) -> str:
        """Build PostgreSQL upsert for entity vectors with ON CONFLICT."""
        return """
               INSERT INTO entity_vectors (neo4j_id, embedding, model_id)
               VALUES (:neo4j_id, CAST(:embedding AS vector), :model_id) ON CONFLICT (neo4j_id)
            DO
               UPDATE SET embedding = EXCLUDED.embedding, model_id = EXCLUDED.model_id, updated_at = NOW() \
               """


class DuckDBVectorQueryBuilder:
    """DuckDB implementation of VectorQueryBuilder."""

    @property
    def database_type(self) -> DatabaseType:
        """Get DuckDB database type."""
        return DatabaseType.DUCKDB

    def get_session_init_statements(self) -> list[str]:
        """No initialization needed for DuckDB in tests."""
        return []

    def format_embedding_param(self, embedding: list[float]) -> list[float]:
        """Return embedding as-is for SQLAlchemy parameter binding.

        DuckDB's SQLAlchemy driver accepts Python lists directly when
        using CAST() syntax.
        """
        return embedding

    def build_similarity_expression(self, column: str) -> str:
        """Build DuckDB cosine similarity expression."""
        return f"array_cosine_similarity({column}, CAST(:embedding AS FLOAT[1024]))"

    def build_vector_cast(self, param: str) -> str:
        """Build DuckDB vector cast."""
        return f"CAST({param} AS FLOAT[1024])"

    def build_upsert_article_vector_query(self) -> str:
        """Build DuckDB upsert with ON CONFLICT.

        Note: DuckDB requires explicit conflict target when table has multiple
        UNIQUE/PRIMARY KEY constraints. article_vectors uses composite PK (article_id, vector_type).
        """
        return """
               INSERT INTO article_vectors (article_id, vector_type, embedding, model_id)
               VALUES (:article_id, :vector_type, CAST(:embedding AS FLOAT[1024]),
                       :model_id) ON CONFLICT (article_id, vector_type) DO
               UPDATE SET
                   embedding = EXCLUDED.embedding,
                   model_id = EXCLUDED.model_id,
                   created_at = NOW() \
               """

    def build_upsert_article_vector_batch_query(self, batch_size: int) -> str:
        """DuckDB doesn't support batch upsert efficiently."""
        raise NotImplementedError("DuckDB doesn't support batch upsert; use individual inserts")

    def build_upsert_entity_vector_query(self) -> str:
        """Build DuckDB upsert for entity vectors with ON CONFLICT.

        Note: DuckDB requires explicit conflict target when table has multiple
        UNIQUE/PRIMARY KEY constraints. entity_vectors has PK (id) + UNIQUE (neo4j_id).
        """
        return """
               INSERT INTO entity_vectors (neo4j_id, embedding, model_id)
               VALUES (:neo4j_id, CAST(:embedding AS FLOAT[1024]), :model_id) ON CONFLICT (neo4j_id) DO
               UPDATE SET
                   embedding = EXCLUDED.embedding,
                   model_id = EXCLUDED.model_id,
                   updated_at = NOW() \
               """

    def build_find_similar_articles_query(self, config: SimilarityQuery) -> str:
        """Build DuckDB cosine similarity search."""
        # Validate inputs for security
        validate_limit(config.limit)
        validate_threshold(config.threshold)
        VectorType(config.vector_type)  # Validate against enum

        similarity_expr = self.build_similarity_expression("av.embedding")

        # Build WHERE conditions based on filter flags
        conditions = ["av.vector_type = :vector_type"]

        if config.filter_by_category:
            conditions.append(f"a.category = {config.category_param}")

        if config.filter_by_model_id:
            conditions.append(f"av.model_id = {config.model_id_param}")

        conditions.append(f"{similarity_expr} >= :threshold")

        where_clause = " AND ".join(conditions)

        return f"""
            SELECT
                CAST(a.id AS VARCHAR) AS article_id,
                a.category,
                {similarity_expr} AS similarity,
                a.publish_time,
                a.created_at
            FROM article_vectors av
            JOIN articles a ON a.id = av.article_id
            WHERE {where_clause}
            ORDER BY {similarity_expr} DESC
            LIMIT {config.limit}
        """

    def build_find_similar_entities_query(self, config: EntitySimilarityQuery) -> str:
        """Build DuckDB entity similarity search."""
        # Validate inputs for security
        validate_limit(config.limit)
        validate_threshold(config.threshold)

        similarity_expr = self.build_similarity_expression("embedding")
        return f"""
            SELECT
                neo4j_id,
                {similarity_expr} AS similarity
            FROM entity_vectors
            WHERE {similarity_expr} >= {config.threshold}
            ORDER BY {similarity_expr} DESC
            LIMIT {config.limit}
        """

    def build_array_contains_expression(self, column: str, param: str) -> str:
        """DuckDB unnest expression for array containment."""
        return f"{column} IN (SELECT unnest({param}))"


def create_vector_query_builder(db_type: str | DatabaseType) -> VectorQueryBuilder:
    """Create appropriate query builder for database type.

    Args:
        db_type: Database type string or enum value ('postgres', 'postgresql', or 'duckdb').

    Returns:
        Database-specific VectorQueryBuilder implementation.

    Raises:
        ValueError: If database type is not supported.
    """
    if isinstance(db_type, str):
        # Normalize aliases: "postgresql" -> "postgres"
        db_type_lower = db_type.lower()
        if db_type_lower == "postgresql":
            db_type_lower = "postgres"
        try:
            db_type = DatabaseType(db_type_lower)
        except ValueError:
            raise ValueError(f"Unsupported database type: {db_type}") from None

    if db_type == DatabaseType.POSTGRES:
        return PgVectorQueryBuilder()
    elif db_type == DatabaseType.DUCKDB:
        return DuckDBVectorQueryBuilder()
    else:
        raise ValueError(f"Unsupported database type: {db_type}")
