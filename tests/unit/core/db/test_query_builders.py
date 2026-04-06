# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for QueryBuilder pattern."""

import pytest

from core.db.query_builders import (
    DatabaseType,
    DuckDBVectorQueryBuilder,
    EntitySimilarityQuery,
    PgVectorQueryBuilder,
    SimilarityQuery,
    VectorQueryBuilder,
    create_vector_query_builder,
)


class TestDatabaseTypeEnum:
    """Tests for DatabaseType enum."""

    def test_postgres_value(self) -> None:
        assert DatabaseType.POSTGRES.value == "postgres"

    def test_duckdb_value(self) -> None:
        assert DatabaseType.DUCKDB.value == "duckdb"

    def test_from_string(self) -> None:
        assert DatabaseType("postgres") == DatabaseType.POSTGRES
        assert DatabaseType("duckdb") == DatabaseType.DUCKDB


class TestSimilarityQuery:
    """Tests for SimilarityQuery dataclass."""

    def test_default_values(self) -> None:
        config = SimilarityQuery()
        assert config.embedding_param == ":embedding"
        assert config.threshold == 0.80
        assert config.limit == 20
        assert config.category_param == ":category"
        assert config.model_id_param == ":model_id"
        assert config.vector_type == "content"

    def test_custom_values(self) -> None:
        config = SimilarityQuery(
            threshold=0.9,
            limit=50,
            vector_type="title",
        )
        assert config.threshold == 0.9
        assert config.limit == 50
        assert config.vector_type == "title"

    def test_frozen(self) -> None:
        config = SimilarityQuery()
        with pytest.raises(AttributeError):
            config.threshold = 0.5  # type: ignore[misc]


class TestEntitySimilarityQuery:
    """Tests for EntitySimilarityQuery dataclass."""

    def test_default_values(self) -> None:
        config = EntitySimilarityQuery()
        assert config.embedding_param == ":embedding"
        assert config.threshold == 0.85
        assert config.limit == 5

    def test_custom_values(self) -> None:
        config = EntitySimilarityQuery(threshold=0.95, limit=10)
        assert config.threshold == 0.95
        assert config.limit == 10


class TestPgVectorQueryBuilder:
    """Tests for PostgreSQL pgvector query builder."""

    @pytest.fixture
    def builder(self) -> PgVectorQueryBuilder:
        return PgVectorQueryBuilder()

    def test_database_type(self, builder: PgVectorQueryBuilder) -> None:
        assert builder.database_type == DatabaseType.POSTGRES

    def test_build_similarity_expression(self, builder: PgVectorQueryBuilder) -> None:
        result = builder.build_similarity_expression("embedding")
        assert "<=>" in result
        assert "cast(:embedding as vector)" in result
        assert result.startswith("1 - (")

    def test_build_vector_cast(self, builder: PgVectorQueryBuilder) -> None:
        result = builder.build_vector_cast(":emb")
        assert result == "cast(:emb as vector)"

    def test_build_upsert_article_vector_query(self, builder: PgVectorQueryBuilder) -> None:
        result = builder.build_upsert_article_vector_query()
        assert "INSERT INTO article_vectors" in result
        assert "ON CONFLICT" in result
        assert "DO UPDATE SET" in result

    def test_build_upsert_article_vector_batch_query(self, builder: PgVectorQueryBuilder) -> None:
        result = builder.build_upsert_article_vector_batch_query(3)
        assert ":article_id_0" in result
        assert ":article_id_1" in result
        assert ":article_id_2" in result
        assert "ON CONFLICT" in result

    def test_build_find_similar_articles_query(self, builder: PgVectorQueryBuilder) -> None:
        config = SimilarityQuery(threshold=0.8, limit=10)
        result = builder.build_find_similar_articles_query(config)
        assert "SELECT" in result
        assert "FROM article_vectors av" in result
        assert "JOIN articles a" in result
        assert "ORDER BY similarity DESC" in result
        assert "LIMIT 10" in result

    def test_build_find_similar_entities_query(self, builder: PgVectorQueryBuilder) -> None:
        config = EntitySimilarityQuery(threshold=0.9, limit=3)
        result = builder.build_find_similar_entities_query(config)
        assert "SELECT" in result
        assert "FROM entity_vectors" in result
        assert "LIMIT 3" in result

    def test_get_session_init_statements(self, builder: PgVectorQueryBuilder) -> None:
        statements = builder.get_session_init_statements()
        assert len(statements) == 1
        assert "SET hnsw.ef_search" in statements[0]

    def test_format_embedding_param(self, builder: PgVectorQueryBuilder) -> None:
        embedding = [0.1, 0.2, 0.3]
        result = builder.format_embedding_param(embedding)
        assert isinstance(result, str)
        assert result == "[0.1,0.2,0.3]"

    def test_build_array_contains_expression(self, builder: PgVectorQueryBuilder) -> None:
        result = builder.build_array_contains_expression("id", ":ids")
        assert result == "id = ANY(:ids)"


class TestDuckDBVectorQueryBuilder:
    """Tests for DuckDB query builder."""

    @pytest.fixture
    def builder(self) -> DuckDBVectorQueryBuilder:
        return DuckDBVectorQueryBuilder()

    def test_database_type(self, builder: DuckDBVectorQueryBuilder) -> None:
        assert builder.database_type == DatabaseType.DUCKDB

    def test_build_similarity_expression(self, builder: DuckDBVectorQueryBuilder) -> None:
        result = builder.build_similarity_expression("embedding")
        assert "array_cosine_similarity" in result
        assert "FLOAT[1024]" in result

    def test_build_vector_cast(self, builder: DuckDBVectorQueryBuilder) -> None:
        result = builder.build_vector_cast(":emb")
        assert result == "CAST(:emb AS FLOAT[1024])"

    def test_build_upsert_article_vector_query(self, builder: DuckDBVectorQueryBuilder) -> None:
        result = builder.build_upsert_article_vector_query()
        assert "INSERT OR REPLACE" in result
        assert "article_vectors" in result

    def test_build_upsert_article_vector_batch_query_raises(
        self, builder: DuckDBVectorQueryBuilder
    ) -> None:
        with pytest.raises(NotImplementedError):
            builder.build_upsert_article_vector_batch_query(5)

    def test_build_find_similar_articles_query(self, builder: DuckDBVectorQueryBuilder) -> None:
        config = SimilarityQuery(threshold=0.75, limit=15)
        result = builder.build_find_similar_articles_query(config)
        assert "SELECT" in result
        assert "array_cosine_similarity" in result
        assert "LIMIT 15" in result

    def test_build_find_similar_entities_query(self, builder: DuckDBVectorQueryBuilder) -> None:
        config = EntitySimilarityQuery(threshold=0.8, limit=7)
        result = builder.build_find_similar_entities_query(config)
        assert "SELECT" in result
        assert "FROM entity_vectors" in result

    def test_get_session_init_statements_empty(self, builder: DuckDBVectorQueryBuilder) -> None:
        statements = builder.get_session_init_statements()
        assert statements == []

    def test_format_embedding_param(self, builder: DuckDBVectorQueryBuilder) -> None:
        embedding = [0.1, 0.2, 0.3]
        result = builder.format_embedding_param(embedding)
        assert isinstance(result, list)
        assert result == embedding

    def test_build_array_contains_expression(self, builder: DuckDBVectorQueryBuilder) -> None:
        result = builder.build_array_contains_expression("id", ":ids")
        assert "SELECT unnest(:ids)" in result


class TestCreateVectorQueryBuilder:
    """Tests for factory function."""

    def test_create_postgres_builder_from_enum(self) -> None:
        builder = create_vector_query_builder(DatabaseType.POSTGRES)
        assert isinstance(builder, PgVectorQueryBuilder)

    def test_create_duckdb_builder_from_enum(self) -> None:
        builder = create_vector_query_builder(DatabaseType.DUCKDB)
        assert isinstance(builder, DuckDBVectorQueryBuilder)

    def test_create_postgres_builder_from_string(self) -> None:
        builder = create_vector_query_builder("postgres")
        assert isinstance(builder, PgVectorQueryBuilder)

    def test_create_duckdb_builder_from_string(self) -> None:
        builder = create_vector_query_builder("duckdb")
        assert isinstance(builder, DuckDBVectorQueryBuilder)

    def test_create_builder_case_insensitive(self) -> None:
        builder = create_vector_query_builder("POSTGRES")
        assert isinstance(builder, PgVectorQueryBuilder)

    def test_create_builder_invalid_type(self) -> None:
        with pytest.raises(ValueError, match="Unsupported database type"):
            create_vector_query_builder("invalid")


class TestQueryBuilderProtocol:
    """Tests for VectorQueryBuilder protocol compliance."""

    def test_postgres_builder_implements_protocol(self) -> None:
        builder = PgVectorQueryBuilder()
        # Protocol is structural, just verify all methods exist
        assert hasattr(builder, "database_type")
        assert hasattr(builder, "build_similarity_expression")
        assert hasattr(builder, "build_vector_cast")
        assert hasattr(builder, "build_upsert_article_vector_query")
        assert hasattr(builder, "build_find_similar_articles_query")
        assert hasattr(builder, "build_find_similar_entities_query")
        assert hasattr(builder, "get_session_init_statements")
        assert hasattr(builder, "format_embedding_param")
        assert hasattr(builder, "build_array_contains_expression")

    def test_duckdb_builder_implements_protocol(self) -> None:
        builder = DuckDBVectorQueryBuilder()
        assert hasattr(builder, "database_type")
        assert hasattr(builder, "build_similarity_expression")
        assert hasattr(builder, "build_vector_cast")
        assert hasattr(builder, "build_upsert_article_vector_query")
        assert hasattr(builder, "build_find_similar_articles_query")
        assert hasattr(builder, "build_find_similar_entities_query")
        assert hasattr(builder, "get_session_init_statements")
        assert hasattr(builder, "format_embedding_param")
        assert hasattr(builder, "build_array_contains_expression")


class TestQueryOutputComparison:
    """Tests comparing query outputs between builders."""

    def test_similarity_expression_differs(self) -> None:
        pg = PgVectorQueryBuilder()
        duck = DuckDBVectorQueryBuilder()

        pg_sim = pg.build_similarity_expression()
        duck_sim = duck.build_similarity_expression()

        # Both should calculate similarity but with different syntax
        assert "<=>" in pg_sim
        assert "array_cosine_similarity" in duck_sim

    def test_vector_cast_differs(self) -> None:
        pg = PgVectorQueryBuilder()
        duck = DuckDBVectorQueryBuilder()

        pg_cast = pg.build_vector_cast()
        duck_cast = duck.build_vector_cast()

        assert "vector" in pg_cast
        assert "FLOAT[1024]" in duck_cast

    def test_upsert_syntax_differs(self) -> None:
        pg = PgVectorQueryBuilder()
        duck = DuckDBVectorQueryBuilder()

        pg_upsert = pg.build_upsert_article_vector_query()
        duck_upsert = duck.build_upsert_article_vector_query()

        assert "ON CONFLICT" in pg_upsert
        assert "INSERT OR REPLACE" in duck_upsert

    def test_session_init_differs(self) -> None:
        pg = PgVectorQueryBuilder()
        duck = DuckDBVectorQueryBuilder()

        pg_init = pg.get_session_init_statements()
        duck_init = duck.get_session_init_statements()

        assert len(pg_init) == 1
        assert len(duck_init) == 0

    def test_embedding_format_differs(self) -> None:
        pg = PgVectorQueryBuilder()
        duck = DuckDBVectorQueryBuilder()

        emb = [0.1, 0.2, 0.3]

        pg_formatted = pg.format_embedding_param(emb)
        duck_formatted = duck.format_embedding_param(emb)

        assert isinstance(pg_formatted, str)
        assert isinstance(duck_formatted, list)

    def test_array_contains_differs(self) -> None:
        pg = PgVectorQueryBuilder()
        duck = DuckDBVectorQueryBuilder()

        pg_expr = pg.build_array_contains_expression("id", ":ids")
        duck_expr = duck.build_array_contains_expression("id", ":ids")

        assert "ANY" in pg_expr
        assert "unnest" in duck_expr
