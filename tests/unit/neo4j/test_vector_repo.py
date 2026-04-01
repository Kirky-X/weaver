# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for VectorRepo."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.storage.postgres.vector_repo import SimilarArticle, SimilarEntity, VectorRepo


class MockRow:
    """Mimics a SQLAlchemy Row with _mapping attribute."""

    def __init__(self, data: dict):
        object.__setattr__(self, "_mapping", data)

    def __getattr__(self, name: str) -> object:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._mapping.get(name)


def _make_mock_pool(
    sim_rows: list[MockRow] | None = None, text_rows: list[MockRow] | None = None
) -> MagicMock:
    """Build a mock PostgresPool."""
    if sim_rows is None:
        sim_rows = []
    if text_rows is None:
        text_rows = sim_rows

    mock_session = MagicMock()
    _sim_rows = sim_rows
    _text_rows = text_rows
    _execute_tracker = AsyncMock()

    async def mock_execute(query, params=None):
        sql = str(query)
        result = MagicMock()
        if (
            "av.embedding <=>" in sql
            or "similarity" in sql.lower()
            or ("article_vectors" in sql.lower() and "delete" not in sql.lower())
        ):
            result.__iter__ = lambda self: iter(_sim_rows)
        elif "articles a" in sql.lower():
            result.__iter__ = lambda self: iter(_text_rows)
        else:
            result.__iter__ = lambda self: iter([])
        _execute_tracker(query, params)
        result.rowcount = len(_sim_rows)
        result.scalar = MagicMock(return_value=_sim_rows[0] if _sim_rows else None)
        result.scalar_one_or_none = MagicMock(return_value=_sim_rows[0] if _sim_rows else None)
        return result

    mock_session.execute = mock_execute
    mock_session.commit = AsyncMock()
    mock_pool = MagicMock()
    mock_pool.session.return_value.__aenter__.return_value = mock_session
    mock_pool._execute_tracker = _execute_tracker
    return mock_pool


class TestFindSimilarHybrid:
    """Tests for VectorRepo.find_similar_hybrid()."""

    @pytest.mark.asyncio
    async def test_find_similar_hybrid_returns_nonempty_when_vec_sim_below_threshold(self):
        """Even with vec_sim=0.3, keyword hits push hybrid above 0."""
        sim_rows = [
            MockRow(
                {
                    "article_id": "article-001",
                    "category": "tech",
                    "similarity": 0.3,
                }
            ),
        ]
        text_rows = [
            MockRow(
                {
                    "article_id": "article-001",
                    "title": "AI is transforming the industry",
                    "body": "",
                }
            ),
        ]
        mock_pool = _make_mock_pool(sim_rows, text_rows)

        repo = VectorRepo(pool=mock_pool)
        result = await repo.find_similar_hybrid(
            embedding=[0.1] * 1024,
            query_tokens=["AI"],
            category=None,
            min_score=0.0,
            limit=20,
        )

        assert len(result) == 1
        article = result[0]
        assert article.article_id == "article-001"
        assert article.category == "tech"
        assert article.hybrid_score is not None
        assert abs(article.hybrid_score - 0.51) < 0.01
        assert article.similarity == 0.3

    @pytest.mark.asyncio
    async def test_find_similar_hybrid_keyword_overlap_changes_ranking(self):
        """Article with more keyword matches ranks higher even with lower vec_sim."""
        sim_rows = [
            MockRow(
                {
                    "article_id": "article-A",
                    "category": "tech",
                    "similarity": 0.52,
                }
            ),
            MockRow(
                {
                    "article_id": "article-B",
                    "category": "tech",
                    "similarity": 0.455,
                }
            ),
        ]
        text_rows = [
            MockRow(
                {
                    "article_id": "article-A",
                    "title": "小米投资新兴公司",
                    "body": "",
                }
            ),
            MockRow(
                {
                    "article_id": "article-B",
                    "title": "小米投资科技领域",
                    "body": "",
                }
            ),
        ]
        mock_pool = _make_mock_pool(sim_rows, text_rows)

        repo = VectorRepo(pool=mock_pool)
        result = await repo.find_similar_hybrid(
            embedding=[0.1] * 1024,
            query_tokens=["小米", "投资", "科技"],
            category=None,
            min_score=0.0,
            limit=20,
        )

        assert len(result) == 2
        assert result[0].article_id == "article-B"
        assert result[1].article_id == "article-A"
        assert result[0].hybrid_score > result[1].hybrid_score

    @pytest.mark.asyncio
    async def test_find_similar_hybrid_min_score_filter(self):
        """Candidates with hybrid_score below min_score are excluded."""
        sim_rows = [
            MockRow(
                {
                    "article_id": "article-low",
                    "category": "tech",
                    "similarity": 0.5,
                }
            ),
            MockRow(
                {
                    "article_id": "article-high",
                    "category": "tech",
                    "similarity": 0.8,
                }
            ),
        ]
        text_rows = [
            MockRow(
                {
                    "article_id": "article-low",
                    "title": "unrelated content",
                    "body": "",
                }
            ),
            MockRow(
                {
                    "article_id": "article-high",
                    "title": "AI and machine learning",
                    "body": "",
                }
            ),
        ]
        mock_pool = _make_mock_pool(sim_rows, text_rows)

        repo = VectorRepo(pool=mock_pool)
        result = await repo.find_similar_hybrid(
            embedding=[0.1] * 1024,
            query_tokens=["AI"],
            category=None,
            min_score=0.6,
            limit=20,
        )

        assert len(result) == 1
        assert result[0].article_id == "article-high"

    @pytest.mark.asyncio
    async def test_find_similar_hybrid_empty_when_no_candidates(self):
        """Returns empty list when the database query returns zero rows."""
        mock_pool = _make_mock_pool([])

        repo = VectorRepo(pool=mock_pool)
        result = await repo.find_similar_hybrid(
            embedding=[0.1] * 1024,
            query_tokens=["AI"],
            category=None,
            min_score=0.0,
            limit=20,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_find_similar_hybrid_category_filter(self):
        """When category is provided, the SQL query includes a category filter."""
        sim_rows = [
            MockRow(
                {
                    "article_id": "article-cat",
                    "category": "finance",
                    "similarity": 0.7,
                }
            ),
        ]
        text_rows = [
            MockRow(
                {
                    "article_id": "article-cat",
                    "title": "stock market report",
                    "body": "",
                }
            ),
        ]
        mock_pool = _make_mock_pool(sim_rows, text_rows)

        repo = VectorRepo(pool=mock_pool)
        result = await repo.find_similar_hybrid(
            embedding=[0.1] * 1024,
            query_tokens=["stock"],
            category="finance",
            min_score=0.0,
            limit=20,
        )

        assert mock_pool._execute_tracker.call_count >= 2
        assert len(result) == 1
        assert result[0].article_id == "article-cat"
        assert result[0].category == "finance"


class TestUpsertArticleVectors:
    """Tests for VectorRepo.upsert_article_vectors()."""

    @pytest.mark.asyncio
    async def test_upsert_article_vectors_title_only(self):
        """Test upsert with only title embedding."""
        mock_pool = _make_mock_pool()
        repo = VectorRepo(pool=mock_pool)

        article_id = uuid.uuid4()
        await repo.upsert_article_vectors(
            article_id=article_id,
            title_embedding=[0.1] * 1024,
            content_embedding=None,
        )

        assert mock_pool._execute_tracker.call_count >= 1

    @pytest.mark.asyncio
    async def test_upsert_article_vectors_both_embeddings(self):
        """Test upsert with both embeddings."""
        mock_pool = _make_mock_pool()
        repo = VectorRepo(pool=mock_pool)

        article_id = uuid.uuid4()
        await repo.upsert_article_vectors(
            article_id=article_id,
            title_embedding=[0.1] * 1024,
            content_embedding=[0.2] * 1024,
            model_id="qwen3-embedding:0.6b",
        )

        assert mock_pool._execute_tracker.call_count >= 1


class TestBulkUpsertArticleVectors:
    """Tests for VectorRepo.bulk_upsert_article_vectors()."""

    @pytest.mark.asyncio
    async def test_bulk_upsert_empty_list(self):
        """Test bulk upsert with empty list."""
        mock_pool = _make_mock_pool()
        repo = VectorRepo(pool=mock_pool)

        result = await repo.bulk_upsert_article_vectors([])

        assert result == 0

    @pytest.mark.asyncio
    async def test_bulk_upsert_single_article(self):
        """Test bulk upsert with single article."""
        mock_pool = _make_mock_pool()
        repo = VectorRepo(pool=mock_pool)

        article_id = uuid.uuid4()
        articles = [
            (article_id, [0.1] * 1024, [0.2] * 1024, "text-embedding-3-large"),
        ]

        result = await repo.bulk_upsert_article_vectors(articles)

        assert mock_pool._execute_tracker.call_count >= 1

    @pytest.mark.asyncio
    async def test_bulk_upsert_multiple_articles(self):
        """Test bulk upsert with multiple articles."""
        mock_pool = _make_mock_pool()
        repo = VectorRepo(pool=mock_pool)

        articles = [
            (uuid.uuid4(), [0.1] * 1024, [0.2] * 1024, "model-1"),
            (uuid.uuid4(), [0.3] * 1024, None, "model-1"),
            (uuid.uuid4(), None, [0.4] * 1024, "model-1"),
        ]

        await repo.bulk_upsert_article_vectors(articles)

        assert mock_pool._execute_tracker.call_count >= 1


class TestFindSimilar:
    """Tests for VectorRepo.find_similar()."""

    @pytest.mark.asyncio
    async def test_find_similar_returns_results(self):
        """Test find_similar returns matching articles."""
        sim_rows = [
            MockRow(
                {
                    "article_id": "article-001",
                    "category": "tech",
                    "similarity": 0.85,
                }
            ),
        ]
        mock_pool = _make_mock_pool(sim_rows)

        repo = VectorRepo(pool=mock_pool)
        result = await repo.find_similar(
            embedding=[0.1] * 1024,
            category=None,
            threshold=0.8,
            limit=10,
        )

        assert len(result) == 1
        assert result[0].article_id == "article-001"
        assert result[0].similarity == 0.85

    @pytest.mark.asyncio
    async def test_find_similar_empty_results(self):
        """Test find_similar returns empty list when no matches."""
        mock_pool = _make_mock_pool([])

        repo = VectorRepo(pool=mock_pool)
        result = await repo.find_similar(
            embedding=[0.1] * 1024,
            category=None,
            threshold=0.9,
            limit=10,
        )

        assert result == []


class TestBatchFindSimilar:
    """Tests for VectorRepo.batch_find_similar()."""

    @pytest.mark.asyncio
    async def test_batch_find_similar_empty_queries(self):
        """Test batch find with empty queries list."""
        mock_pool = _make_mock_pool()
        repo = VectorRepo(pool=mock_pool)

        result = await repo.batch_find_similar([])

        assert result == {}

    @pytest.mark.asyncio
    async def test_batch_find_similar_multiple_queries(self):
        """Test batch find with multiple queries."""
        sim_rows = [
            MockRow(
                {
                    "article_id": "article-001",
                    "category": "tech",
                    "similarity": 0.85,
                }
            ),
        ]
        mock_pool = _make_mock_pool(sim_rows)
        repo = VectorRepo(pool=mock_pool)

        query_id1 = uuid.uuid4()
        query_id2 = uuid.uuid4()
        queries = [
            (query_id1, [0.1] * 1024),
            (query_id2, [0.2] * 1024),
        ]

        result = await repo.batch_find_similar(queries)

        assert query_id1 in result
        assert query_id2 in result


class TestFindSimilarEntities:
    """Tests for VectorRepo.find_similar_entities()."""

    @pytest.mark.asyncio
    async def test_find_similar_entities_returns_results(self):
        """Test find_similar_entities returns matching entities."""
        sim_rows = [
            MockRow(
                {
                    "neo4j_id": "entity-001",
                    "similarity": 0.92,
                }
            ),
        ]
        mock_pool = _make_mock_pool(sim_rows)
        repo = VectorRepo(pool=mock_pool)

        result = await repo.find_similar_entities(
            embedding=[0.1] * 1024,
            threshold=0.85,
            limit=5,
        )

        assert len(result) == 1
        assert result[0].neo4j_id == "entity-001"
        assert result[0].similarity == 0.92


class TestDeleteArticleVectors:
    """Tests for VectorRepo.delete_article_vectors_by_article_ids()."""

    @pytest.mark.asyncio
    async def test_delete_empty_list(self):
        """Test delete with empty list."""
        mock_pool = _make_mock_pool()
        repo = VectorRepo(pool=mock_pool)

        result = await repo.delete_article_vectors_by_article_ids([])

        assert result == 0

    @pytest.mark.asyncio
    async def test_delete_multiple_articles(self):
        """Test delete with multiple article IDs."""
        mock_pool = _make_mock_pool()
        repo = VectorRepo(pool=mock_pool)

        article_ids = [uuid.uuid4(), uuid.uuid4()]
        await repo.delete_article_vectors_by_article_ids(article_ids)

        assert mock_pool._execute_tracker.call_count >= 1


class TestDeleteEntityVectors:
    """Tests for VectorRepo.delete_entity_vectors_by_neo4j_ids()."""

    @pytest.mark.asyncio
    async def test_delete_empty_list(self):
        """Test delete with empty list."""
        mock_pool = _make_mock_pool()
        repo = VectorRepo(pool=mock_pool)

        result = await repo.delete_entity_vectors_by_neo4j_ids([])

        assert result == 0

    @pytest.mark.asyncio
    async def test_delete_multiple_entities(self):
        """Test delete with multiple neo4j IDs."""
        mock_pool = _make_mock_pool()
        repo = VectorRepo(pool=mock_pool)

        neo4j_ids = ["entity-1", "entity-2"]
        await repo.delete_entity_vectors_by_neo4j_ids(neo4j_ids)

        assert mock_pool._execute_tracker.call_count >= 1


class TestUpdateEntityVectorsByTempKeys:
    """Tests for VectorRepo.update_entity_vectors_by_temp_keys()."""

    @pytest.mark.asyncio
    async def test_update_empty_dict(self):
        """Test update with empty dict."""
        mock_pool = _make_mock_pool()
        repo = VectorRepo(pool=mock_pool)

        result = await repo.update_entity_vectors_by_temp_keys({})

        assert result == 0

    @pytest.mark.asyncio
    async def test_update_multiple_keys(self):
        """Test update with multiple temp keys."""
        mock_pool = _make_mock_pool()
        repo = VectorRepo(pool=mock_pool)

        temp_key_to_neo4j = {
            "temp-1": "neo4j-1",
            "temp-2": "neo4j-2",
        }
        await repo.update_entity_vectors_by_temp_keys(temp_key_to_neo4j)

        assert mock_pool._execute_tracker.call_count >= 1


class TestCountEntitiesWithValidNeo4jIds:
    """Tests for VectorRepo.count_entities_with_valid_neo4j_ids()."""

    @pytest.mark.asyncio
    async def test_count_returns_number(self):
        """Test count returns a number."""
        mock_pool = _make_mock_pool()
        # Override scalar to return a count
        mock_session = mock_pool.session.return_value.__aenter__.return_value
        mock_session.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=10)
        mock_session.execute.return_value = mock_result

        repo = VectorRepo(pool=mock_pool)
        result = await repo.count_entities_with_valid_neo4j_ids()

        assert result == 10


class TestSimilarArticleDataclass:
    """Tests for SimilarArticle dataclass."""

    def test_similar_article_creation(self):
        """Test creating SimilarArticle instance."""
        from datetime import datetime

        article = SimilarArticle(
            article_id="test-123",
            category="tech",
            similarity=0.85,
            hybrid_score=0.9,
            publish_time=datetime.now(),
        )

        assert article.article_id == "test-123"
        assert article.category == "tech"
        assert article.similarity == 0.85
        assert article.hybrid_score == 0.9

    def test_similar_article_defaults(self):
        """Test SimilarArticle with default values."""
        article = SimilarArticle(
            article_id="test-123",
            category="tech",
            similarity=0.85,
        )

        assert article.hybrid_score is None
        assert article.publish_time is None
        assert article.created_at is None


class TestSimilarEntityDataclass:
    """Tests for SimilarEntity dataclass."""

    def test_similar_entity_creation(self):
        """Test creating SimilarEntity instance."""
        entity = SimilarEntity(
            neo4j_id="entity-123",
            similarity=0.92,
        )

        assert entity.neo4j_id == "entity-123"
        assert entity.similarity == 0.92
