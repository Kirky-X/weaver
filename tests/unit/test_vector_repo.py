# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for VectorRepo.find_similar_hybrid()."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.storage.vector_repo import VectorRepo


class MockRow:
    """Mimics a SQLAlchemy Row with _mapping attribute."""

    def __init__(self, data: dict):
        self._mapping = data


def _make_mock_pool(rows: list[MockRow]) -> MagicMock:
    """Build a mock PostgresPool that returns the given rows on execute."""
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.__iter__ = lambda self: iter(rows)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_pool = MagicMock()
    mock_pool.session.return_value.__aenter__.return_value = mock_session
    return mock_pool


class TestFindSimilarHybrid:
    """Tests for VectorRepo.find_similar_hybrid()."""

    # ── 1. Returns results when vector sim is below old threshold ───────────

    @pytest.mark.asyncio
    async def test_find_similar_hybrid_returns_nonempty_when_vec_sim_below_threshold(self):
        """Even with vec_sim=0.3 (< old 0.75 threshold), keyword hits push hybrid above 0."""
        mock_pool = _make_mock_pool(
            [
                MockRow(
                    {
                        "article_id": "article-001",
                        "category": "tech",
                        "quality_score": 0.5,
                        "credibility_score": 0.5,
                        "summary": "AI is transforming the industry",
                        "subjects": [],
                        "key_data": [],
                        "vec_sim": 0.3,
                    }
                ),
            ]
        )

        repo = VectorRepo(pool=mock_pool)
        result = await repo.find_similar_hybrid(
            embedding=[0.1] * 1024,
            query_tokens=["AI"],
            category=None,
            min_score=0.0,
            top_k=100,
            limit=20,
        )

        assert len(result) == 1
        article = result[0]
        assert article.article_id == "article-001"
        assert article.category == "tech"
        # hybrid = 0.40*0.3 + 0.30*1.0 + 0.15*0.5 + 0.15*0.5 = 0.12+0.30+0.075+0.075 = 0.57
        assert article.hybrid_score is not None
        assert abs(article.hybrid_score - 0.57) < 0.01
        assert article.similarity == 0.3

    # ── 2. Keyword overlap changes ranking ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_find_similar_hybrid_keyword_overlap_changes_ranking(self):
        """Article with more keyword matches ranks higher even with lower vec_sim."""
        mock_pool = _make_mock_pool(
            [
                # A: vec_sim=0.52, 1 kw hit → hybrid ≈ 0.538
                MockRow(
                    {
                        "article_id": "article-A",
                        "category": "tech",
                        "quality_score": 0.5,
                        "credibility_score": 0.5,
                        "summary": "小米投资新兴公司",
                        "subjects": [],
                        "key_data": [],
                        "vec_sim": 0.52,
                    }
                ),
                # B: vec_sim=0.455, 3 kw hits → hybrid ≈ 0.557  (ranks higher)
                MockRow(
                    {
                        "article_id": "article-B",
                        "category": "tech",
                        "quality_score": 0.5,
                        "credibility_score": 0.5,
                        "summary": "小米投资科技领域",
                        "subjects": [],
                        "key_data": [],
                        "vec_sim": 0.455,
                    }
                ),
            ]
        )

        repo = VectorRepo(pool=mock_pool)
        result = await repo.find_similar_hybrid(
            embedding=[0.1] * 1024,
            query_tokens=["小米", "投资", "科技"],
            category=None,
            min_score=0.0,
            top_k=100,
            limit=20,
        )

        assert len(result) == 2
        # Article B should rank first because more tokens match
        assert result[0].article_id == "article-B"
        assert result[1].article_id == "article-A"
        # Verify hybrid scores
        assert result[0].hybrid_score is not None
        assert result[1].hybrid_score is not None
        assert result[0].hybrid_score > result[1].hybrid_score

    # ── 3. min_score filter ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_find_similar_hybrid_min_score_filter(self):
        """Candidates with hybrid_score below min_score are excluded."""
        mock_pool = _make_mock_pool(
            [
                # hybrid ≈ 0.40*0.5 + 0.30*0.0 + 0.15*0.5 + 0.15*0.5 = 0.32 → filtered out (0.32 < 0.6)
                MockRow(
                    {
                        "article_id": "article-low",
                        "category": "tech",
                        "quality_score": 0.5,
                        "credibility_score": 0.5,
                        "summary": "unrelated content",
                        "subjects": [],
                        "key_data": [],
                        "vec_sim": 0.5,
                    }
                ),
                # hybrid ≈ 0.40*0.8 + 0.30*1.0 + 0.15*0.8 + 0.15*0.8 = 0.32+0.30+0.12+0.12 = 0.86 → kept
                MockRow(
                    {
                        "article_id": "article-high",
                        "category": "tech",
                        "quality_score": 0.8,
                        "credibility_score": 0.8,
                        "summary": "AI and machine learning",
                        "subjects": [],
                        "key_data": [],
                        "vec_sim": 0.8,
                    }
                ),
            ]
        )

        repo = VectorRepo(pool=mock_pool)
        result = await repo.find_similar_hybrid(
            embedding=[0.1] * 1024,
            query_tokens=["AI"],
            category=None,
            min_score=0.6,
            top_k=100,
            limit=20,
        )

        assert len(result) == 1
        assert result[0].article_id == "article-high"

    # ── 4. Empty when DB returns no rows ─────────────────────────────────────

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
            top_k=100,
            limit=20,
        )

        assert result == []

    # ── 5. Category filter ───────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_find_similar_hybrid_category_filter(self):
        """When category is provided, the SQL query includes a category filter."""
        mock_pool = MagicMock()
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter(
            [
                MockRow(
                    {
                        "article_id": "article-cat",
                        "category": "finance",
                        "quality_score": 0.6,
                        "credibility_score": 0.6,
                        "summary": "stock market report",
                        "subjects": [],
                        "key_data": [],
                        "vec_sim": 0.7,
                    }
                ),
            ]
        )
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        repo = VectorRepo(pool=mock_pool)
        result = await repo.find_similar_hybrid(
            embedding=[0.1] * 1024,
            query_tokens=["stock"],
            category="finance",
            min_score=0.0,
            top_k=100,
            limit=20,
        )

        # Verify execute was called at least twice (SET hnsw + actual query)
        assert mock_session.execute.call_count >= 2
        call_args = mock_session.execute.call_args_list[-1]

        # The SQL text is the first positional arg
        sql_text = call_args[0][0].text
        # Verify category filter appears in the query
        assert "category" in sql_text.lower() or "category_type" in sql_text.lower()

        assert len(result) == 1
        assert result[0].article_id == "article-cat"
        assert result[0].category == "finance"
