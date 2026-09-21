# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Unit tests for ArticleReader."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.db import PersistStatus
from modules.storage.postgres.article_reader import ArticleReader
from modules.storage.postgres.article_values import build_core_body_values


def _make_mock_pool(session_rows=None):
    """Build a mock pool with async session context manager."""
    mock_session = AsyncMock()
    mock_result = MagicMock()

    if session_rows is not None:
        mock_result.scalars.return_value.all.return_value = session_rows
        mock_result.scalar_one_or_none.return_value = session_rows[0] if session_rows else None
        mock_result.__iter__ = lambda self: iter(session_rows or [])
    else:
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one_or_none.return_value = None
        mock_result.__iter__ = lambda self: iter([])

    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    pool = MagicMock()
    pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    pool.session.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, mock_session


def _make_raw_article(**overrides):
    """Build a mock RawArticle."""
    raw = MagicMock()
    raw.url = overrides.get("url", "https://example.com/article/1")
    raw.title = overrides.get("title", "Test Title")
    raw.body = overrides.get("body", "A" * 300)
    raw.source_host = overrides.get("source_host", "example.com")
    raw.source_id = overrides.get("source_id")
    raw.publish_time = overrides.get("publish_time")
    raw.description = overrides.get("description")
    return raw


# ── build_core_body_values ──────────────────────────────────────


class TestBuildCoreBodyValues:
    """Tests for the build_core_body_values helper."""

    def test_full_body_uses_body(self):
        """Body >= 200 chars uses raw.body as-is."""
        raw = _make_raw_article(body="X" * 300)
        core_kw, body_kw, source = build_core_body_values(raw)

        assert body_kw["body"] == "X" * 300
        assert source == "full"

    def test_short_body_uses_description(self):
        """Body < 200 chars with description falls back to description."""
        raw = _make_raw_article(body="Short body", description="A" * 300)
        core_kw, body_kw, source = build_core_body_values(raw)

        assert body_kw["body"] == "A" * 300
        assert source == "description"

    def test_short_body_no_description_uses_body(self):
        """Body < 200 chars without description keeps body."""
        raw = _make_raw_article(body="Short body", description=None)
        core_kw, body_kw, source = build_core_body_values(raw)

        assert body_kw["body"] == "Short body"
        assert source == "full"

    def test_content_hash_computed(self):
        """Content hash is computed from title + body."""
        raw = _make_raw_article(title="Title", body="B" * 300)
        core_kw, _, _ = build_core_body_values(raw)

        assert "content_hash" in core_kw
        assert len(core_kw["content_hash"]) > 0

    def test_publish_time_included_when_present(self):
        """publish_time is included in core kwargs when raw has it."""
        dt = datetime(2026, 1, 15, tzinfo=UTC)
        raw = _make_raw_article(publish_time=dt)
        core_kw, _, _ = build_core_body_values(raw)

        assert core_kw["publish_time"] == dt

    def test_publish_time_omitted_when_none(self):
        """publish_time is omitted when raw.publish_time is None."""
        raw = _make_raw_article(publish_time=None)
        core_kw, _, _ = build_core_body_values(raw)

        assert "publish_time" not in core_kw

    def test_persist_status_is_pending(self):
        """Core kwargs set persist_status to PENDING."""
        raw = _make_raw_article()
        core_kw, _, _ = build_core_body_values(raw)

        assert core_kw["persist_status"] == PersistStatus.PENDING


# ── ArticleReader.get ────────────────────────────────────────────


class TestArticleReaderGet:
    """Tests for ArticleReader.get()."""

    @pytest.mark.asyncio
    async def test_get_by_uuid(self):
        """get() with UUID returns article."""
        article = MagicMock()
        pool, session = _make_mock_pool([article])
        reader = ArticleReader(pool)

        uid = uuid.uuid4()
        result = await reader.get(uid)

        assert result is article

    @pytest.mark.asyncio
    async def test_get_by_string_converts_to_uuid(self):
        """get() with string converts to UUID."""
        article = MagicMock()
        pool, session = _make_mock_pool([article])
        reader = ArticleReader(pool)

        uid = uuid.uuid4()
        result = await reader.get(str(uid))

        assert result is article

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(self):
        """get() returns None when article doesn't exist."""
        pool, session = _make_mock_pool([])
        reader = ArticleReader(pool)

        result = await reader.get(uuid.uuid4())

        assert result is None


# ── ArticleReader.get_by_id ──────────────────────────────────────


class TestArticleReaderGetById:
    """Tests for ArticleReader.get_by_id() alias."""

    @pytest.mark.asyncio
    async def test_delegates_to_get(self):
        """get_by_id() delegates to get()."""
        article = MagicMock()
        pool, _ = _make_mock_pool([article])
        reader = ArticleReader(pool)

        result = await reader.get_by_id(uuid.uuid4())

        assert result is article


# ── ArticleReader.get_by_ids ─────────────────────────────────────


class TestArticleReaderGetByIds:
    """Tests for ArticleReader.get_by_ids()."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self):
        """Empty ids list returns empty list without querying."""
        pool, session = _make_mock_pool()
        reader = ArticleReader(pool)

        result = await reader.get_by_ids([])

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_raw_articles(self):
        """get_by_ids() returns list of RawArticle objects."""
        article = MagicMock()
        article.source_url = "https://example.com/1"
        article.title = "Title"
        article.body = "Body"
        article.source_host = "example.com"
        article.publish_time = None

        pool, _ = _make_mock_pool([article])
        reader = ArticleReader(pool)

        ids = [str(uuid.uuid4())]
        result = await reader.get_by_ids(ids)

        assert len(result) == 1
        assert result[0].url == "https://example.com/1"


# ── ArticleReader.get_existing_urls ──────────────────────────────


class TestArticleReaderGetExistingUrls:
    """Tests for ArticleReader.get_existing_urls()."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty_set(self):
        """Empty urls list returns empty set."""
        pool, _ = _make_mock_pool()
        reader = ArticleReader(pool)

        result = await reader.get_existing_urls([])

        assert result == set()

    @pytest.mark.asyncio
    async def test_returns_existing_urls(self):
        """Returns set of URLs found in database."""
        row1 = ("https://example.com/1",)
        pool, _ = _make_mock_pool([row1])
        reader = ArticleReader(pool)

        result = await reader.get_existing_urls(["https://example.com/1", "https://new.com"])

        assert "https://example.com/1" in result


# ── ArticleReader.get_existing_titles ────────────────────────────


class TestArticleReaderGetExistingTitles:
    """Tests for ArticleReader.get_existing_titles()."""

    @pytest.mark.asyncio
    async def test_empty_set_returns_empty(self):
        """Empty titles set returns empty set."""
        pool, _ = _make_mock_pool()
        reader = ArticleReader(pool)

        result = await reader.get_existing_titles(set())

        assert result == set()

    @pytest.mark.asyncio
    async def test_returns_existing_titles(self):
        """Returns set of titles found in database."""
        row1 = ("Existing Title",)
        pool, _ = _make_mock_pool([row1])
        reader = ArticleReader(pool)

        result = await reader.get_existing_titles({"Existing Title", "New Title"})

        assert "Existing Title" in result


# ── ArticleReader.get_pending ────────────────────────────────────


class TestArticleReaderGetPending:
    """Tests for ArticleReader.get_pending()."""

    @pytest.mark.asyncio
    async def test_returns_pending_articles(self):
        """get_pending() returns articles with PENDING status."""
        article = MagicMock()
        pool, _ = _make_mock_pool([article])
        reader = ArticleReader(pool)

        result = await reader.get_pending(limit=10)

        assert len(result) == 1


# ── ArticleReader.get_failed_articles ────────────────────────────


class TestArticleReaderGetFailedArticles:
    """Tests for ArticleReader.get_failed_articles()."""

    @pytest.mark.asyncio
    async def test_returns_failed_articles(self):
        """get_failed_articles() returns articles eligible for retry."""
        article = MagicMock()
        pool, _ = _make_mock_pool([article])
        reader = ArticleReader(pool)

        result = await reader.get_failed_articles(max_retries=3)

        assert len(result) == 1


# ── ArticleReader.fetch_titles_by_pg_ids ─────────────────────────


class TestArticleReaderFetchTitlesByPgIds:
    """Tests for ArticleReader.fetch_titles_by_pg_ids()."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty_dict(self):
        """Empty pg_ids returns empty dict without querying."""
        pool, _ = _make_mock_pool()
        reader = ArticleReader(pool)

        result = await reader.fetch_titles_by_pg_ids([])

        assert result == {}

    @pytest.mark.asyncio
    async def test_invalid_uuids_skipped(self):
        """Invalid UUID strings are skipped with warning."""
        pool, _ = _make_mock_pool()
        reader = ArticleReader(pool)

        result = await reader.fetch_titles_by_pg_ids(["not-a-uuid", "also-invalid"])

        assert result == {}

    @pytest.mark.asyncio
    async def test_valid_ids_return_mapping(self):
        """Valid pg_ids return title mapping."""
        uid = uuid.uuid4()
        row = MagicMock()
        row.__getitem__ = lambda self, idx: [uid, "Test Title", "tech", None, 0.8][idx]

        pool, session = _make_mock_pool()
        # Override session.execute to return iterable result
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([row])
        mock_result.__list__ = lambda self: [row]
        session.execute = AsyncMock(return_value=mock_result)

        reader = ArticleReader(pool)
        result = await reader.fetch_titles_by_pg_ids([str(uid)])

        assert str(uid) in result
        assert result[str(uid)]["title"] == "Test Title"


class TestSplitQueryTerms:
    """Query tokenization for the fallback text search.

    The legacy single ``contains(whole_query)`` term never matched
    natural-language CJK queries; terms are now split (spaCy zh when
    available, whole-run fallback otherwise) and combined with AND.
    """

    def test_ascii_words_split_on_whitespace(self) -> None:
        from modules.storage.postgres.article_reader import _split_query_terms

        assert _split_query_terms("OpenAI GPT news") == ["openai", "gpt", "news"]

    def test_short_cjk_run_stays_whole(self) -> None:
        from modules.storage.postgres.article_reader import _split_query_terms

        assert _split_query_terms("华为") == ["华为"]

    def test_long_cjk_run_segmented_with_spacy(self) -> None:
        """With the zh model installed, a sentence splits into terms that all
        appear as substrings of the original query."""
        pytest.importorskip("spacy")
        try:
            import spacy

            spacy.load("zh_core_web_lg", disable=["ner", "parser", "lemmatizer"])
        except OSError:
            pytest.skip("zh_core_web_lg not installed")

        from modules.storage.postgres.article_reader import _split_query_terms

        terms = _split_query_terms("华为的芯片战略")
        assert terms, "must produce at least one term"
        query = "华为的芯片战略"
        for term in terms:
            assert term in query
            assert len(term) < len(query), "segmented terms must be shorter than the run"

    def test_mixed_cjk_ascii(self) -> None:
        from modules.storage.postgres.article_reader import _split_query_terms

        terms = _split_query_terms("华为 mate60")
        assert "mate60" in terms
        assert "华为" in terms

    def test_empty_returns_empty(self) -> None:
        from modules.storage.postgres.article_reader import _split_query_terms

        assert _split_query_terms("   ") == []
