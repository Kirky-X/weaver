import pytest

from core.mappers.neo4j_entity_mapper import Neo4jEntityMapper
from core.mappers.postgres_article_mapper import PostgresArticleMapper
from core.models.shared import ArticleView, EntityView


class TestMapperMissingFields:
    def test_postgres_mapper_minimal_fields(self):
        result = PostgresArticleMapper().to_view(
            {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "source_url": "https://example.com/article",
                "title": "Minimal Article",
            }
        )
        assert isinstance(result, ArticleView)
        assert result.body is None
        assert result.summary is None
        assert result.category is None
        assert result.score is None
        assert result.sentiment is None
        assert result.credibility_score is None
        assert result.source_host is None
        assert result.verified_by_sources == 0

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

    def test_postgres_mapper_empty_lists(self):
        result = PostgresArticleMapper().to_view(
            {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "source_url": "https://example.com/article",
                "title": "Test",
            }
        )
        assert result.data_conflicts == []

    def test_postgres_mapper_null_subjects_and_key_data(self):
        result = PostgresArticleMapper().to_view(
            {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "source_url": "https://example.com/article",
                "title": "Test",
            }
        )
        assert result.subjects is None
        assert result.key_data is None

    def test_postgres_mapper_partial_credibility(self):
        result = PostgresArticleMapper().to_view(
            {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "source_url": "https://example.com/article",
                "title": "Test",
                "credibility_score": 0.75,
            }
        )
        assert result.credibility_score == 0.75
        assert result.cross_verification is None
