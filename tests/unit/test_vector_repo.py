# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for VectorRepo.find_similar_hybrid()."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.storage.vector_repo import VectorRepo


class MockRow:
    """Mimics a SQLAlchemy Row with _mapping attribute."""

    def __init__(self, data: dict):
        object.__setattr__(self, "_mapping", data)

    def __getattr__(self, name: str) -> object:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._mapping.get(name)


def _make_mock_pool(sim_rows: list[MockRow], text_rows: list[MockRow] | None = None) -> MagicMock:
    """Build a mock PostgresPool.

    sim_rows: rows returned for the find_similar vector query
              (must contain article_id, category, similarity fields).
    text_rows: rows returned for the article text query
               (must contain article_id, title, body fields).
               Defaults to sim_rows if not provided.
    """
    if text_rows is None:
        text_rows = sim_rows

    mock_session = MagicMock()
    _sim_rows = sim_rows
    _text_rows = text_rows
    _execute_tracker = AsyncMock()

    async def mock_execute(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "av.embedding <=>" in sql or "similarity" in sql.lower():
            # find_similar vector query
            result.__iter__ = lambda self: iter(_sim_rows)
        else:
            # article text query
            result.__iter__ = lambda self: iter(_text_rows)
        _execute_tracker(query, params)
        return result

    mock_session.execute = mock_execute
    mock_pool = MagicMock()
    mock_pool.session.return_value.__aenter__.return_value = mock_session
    # Expose tracker for tests that need call_args_list
    mock_pool._execute_tracker = _execute_tracker
    return mock_pool


class TestFindSimilarHybrid:
    """Tests for VectorRepo.find_similar_hybrid()."""

    # ── 1. Returns results when vector sim is below old threshold ───────────

    @pytest.mark.asyncio
    async def test_find_similar_hybrid_returns_nonempty_when_vec_sim_below_threshold(self):
        """Even with vec_sim=0.3 (< old 0.75 threshold), keyword hits push hybrid above 0."""
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
        # hybrid = 0.7*0.3 + 0.3*1.0 = 0.51
        assert article.hybrid_score is not None
        assert abs(article.hybrid_score - 0.51) < 0.01
        assert article.similarity == 0.3

    # ── 2. Keyword overlap changes ranking ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_find_similar_hybrid_keyword_overlap_changes_ranking(self):
        """Article with more keyword matches ranks higher even with lower vec_sim."""
        sim_rows = [
            # A: similarity=0.52, 2/3 kw hits → hybrid ≈ 0.563
            MockRow(
                {
                    "article_id": "article-A",
                    "category": "tech",
                    "similarity": 0.52,
                }
            ),
            # B: similarity=0.455, 3/3 kw hits → hybrid ≈ 0.619 (ranks higher)
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
        sim_rows = [
            # hybrid ≈ 0.7*0.5 + 0.3*0 = 0.35 → filtered out (0.35 < 0.6)
            MockRow(
                {
                    "article_id": "article-low",
                    "category": "tech",
                    "similarity": 0.5,
                }
            ),
            # hybrid ≈ 0.7*0.8 + 0.3*1.0 = 0.86 → kept
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
            limit=20,
        )

        assert result == []

    # ── 5. Category filter ───────────────────────────────────────────────────

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

        # Verify execute was called (SET hnsw + find_similar + text query)
        assert mock_pool._execute_tracker.call_count >= 2
        # find_similar query is the second tracked call (after SET hnsw)
        call_args = mock_pool._execute_tracker.call_args_list[1]
        # The SQL text is the first positional arg
        sql_text = str(call_args[0][0])
        # Verify category filter appears in the find_similar query
        assert "category" in sql_text.lower() or "category_type" in sql_text.lower()
        sql_text = call_args[0][0].text
        # Verify category filter appears in the find_similar query
        assert "category" in sql_text.lower() or "category_type" in sql_text.lower()

        assert len(result) == 1
        assert result[0].article_id == "article-cat"
        assert result[0].category == "finance"
