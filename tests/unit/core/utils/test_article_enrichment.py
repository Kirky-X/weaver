# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""T051 RED: Tests for core.utils.article_enrichment.enrich_articles_with_titles.

After the Article node slim-down (design.md §D2), graph-query callers
receive only ``pg_id`` from the graph DB and must batch-fetch business
fields (title / category / publish_time / score) from the relational DB.
Both ``LocalContextBuilder._get_related_articles`` (Neo4j) and
``LadybugLocalContextBuilder._get_related_articles`` /
``_get_related_articles_by_text`` (LadybugDB) used to inline ~27 lines
of identical title-enrichment logic. This helper extracts that shared
logic and is unit-tested here.

Contract:
    Input:  ``articles: list[dict]``, ``article_repo`` (may be None),
            ``id_fields`` (ordered fallback keys, default ["pg_id","id"]).
    Mutates: each article dict in place, setting title/publish_time/
            category/score from the batched lookup.
    Returns: ``list[str]`` of pg_ids extracted from articles (lowercase),
            so callers can reuse them for ``fetch_bodies_by_pg_ids``.
    Edge:
        - Empty articles -> no DB call, returns []
        - article_repo is None -> degrade (set defaults), no DB call
        - All articles missing id_field -> no DB call, returns []
        - Partial match -> enriched ones get real values; others defaults
        - fetch_titles_by_pg_ids raises -> catch + log + use defaults
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.utils.article_enrichment import enrich_articles_with_titles


class TestEnrichArticlesWithTitlesEmptyAndDegraded:
    """Edge cases for empty input and missing article_repo."""

    @pytest.mark.asyncio
    async def test_empty_articles_returns_empty_list_without_db_call(self) -> None:
        """Empty articles list short-circuits without touching article_repo."""
        repo = MagicMock()
        repo.fetch_titles_by_pg_ids = AsyncMock()

        pg_ids = await enrich_articles_with_titles([], article_repo=repo)

        assert pg_ids == []
        repo.fetch_titles_by_pg_ids.assert_not_called()

    @pytest.mark.asyncio
    async def test_none_article_repo_degrades_with_defaults(self) -> None:
        """When article_repo is None, articles get default title/publish_time."""
        articles = [{"id": "abc"}, {"id": "def"}]

        pg_ids = await enrich_articles_with_titles(articles, article_repo=None)

        assert pg_ids == ["abc", "def"]
        # Defaults applied (setdefault semantics: doesn't overwrite existing).
        assert all(a["title"] == "" for a in articles)
        assert all(a["publish_time"] is None for a in articles)

    @pytest.mark.asyncio
    async def test_none_article_repo_preserves_existing_title(self) -> None:
        """setdefault must NOT overwrite an existing title in degraded mode."""
        articles = [{"id": "abc", "title": "Pre-existing"}]

        await enrich_articles_with_titles(articles, article_repo=None)

        assert articles[0]["title"] == "Pre-existing"

    @pytest.mark.asyncio
    async def test_no_id_field_in_any_article_skips_db_call(self) -> None:
        """Articles with no pg_id/id keys -> no pg_ids -> no DB call."""
        articles = [{"unrelated": "x"}, {"other": "y"}]
        repo = MagicMock()
        repo.fetch_titles_by_pg_ids = AsyncMock()

        pg_ids = await enrich_articles_with_titles(articles, article_repo=repo)

        assert pg_ids == []
        repo.fetch_titles_by_pg_ids.assert_not_called()
        # Defaults still applied
        assert articles[0]["title"] == ""
        assert articles[0]["publish_time"] is None


class TestEnrichArticlesWithTitlesHappyPath:
    """Tests for the normal enrichment flow."""

    @pytest.mark.asyncio
    async def test_all_matched_sets_all_four_fields(self) -> None:
        """When every pg_id matches, all 4 fields are set from meta."""
        publish_time = datetime(2026, 1, 15, 10, 30, tzinfo=UTC)
        articles = [{"id": "AAA"}, {"id": "BBB"}]

        repo = MagicMock()
        repo.fetch_titles_by_pg_ids = AsyncMock(
            return_value={
                "aaa": {
                    "title": "Article A",
                    "category": "tech",
                    "publish_time": publish_time,
                    "score": 0.92,
                },
                "bbb": {
                    "title": "Article B",
                    "category": "finance",
                    "publish_time": None,
                    "score": None,
                },
            }
        )

        pg_ids = await enrich_articles_with_titles(articles, article_repo=repo)

        # pg_ids returned for caller's reuse (bodies fetch).
        assert pg_ids == ["aaa", "bbb"]

        # First article fully enriched.
        assert articles[0]["title"] == "Article A"
        assert articles[0]["category"] == "tech"
        assert articles[0]["publish_time"] == publish_time
        assert articles[0]["score"] == 0.92

        # Second article: None values from meta are propagated (terminal case).
        assert articles[1]["title"] == "Article B"
        assert articles[1]["category"] == "finance"
        assert articles[1]["publish_time"] is None
        assert articles[1]["score"] is None

        # fetch_titles_by_pg_ids called once with all pg_ids.
        repo.fetch_titles_by_pg_ids.assert_awaited_once_with(["aaa", "bbb"])

    @pytest.mark.asyncio
    async def test_partial_match_sets_defaults_for_missing(self) -> None:
        """Articles whose pg_id is missing from titles dict get defaults."""
        articles = [{"id": "found"}, {"id": "missing"}]

        repo = MagicMock()
        repo.fetch_titles_by_pg_ids = AsyncMock(
            return_value={
                "found": {
                    "title": "Found Title",
                    "category": "tech",
                    "publish_time": None,
                    "score": 0.5,
                },
            }
        )

        await enrich_articles_with_titles(articles, article_repo=repo)

        # Found article fully enriched.
        assert articles[0]["title"] == "Found Title"
        assert articles[0]["category"] == "tech"
        assert articles[0]["score"] == 0.5

        # Missing article gets defaults via setdefault.
        assert articles[1]["title"] == ""
        assert articles[1]["publish_time"] is None
        # category/score intentionally NOT setdefault'd (matches legacy behaviour).

    @pytest.mark.asyncio
    async def test_none_found_sets_defaults_for_all(self) -> None:
        """When fetch returns empty dict, all articles get defaults."""
        articles = [{"id": "a"}, {"id": "b"}]

        repo = MagicMock()
        repo.fetch_titles_by_pg_ids = AsyncMock(return_value={})

        await enrich_articles_with_titles(articles, article_repo=repo)

        assert all(a["title"] == "" for a in articles)
        assert all(a["publish_time"] is None for a in articles)


class TestEnrichArticlesWithTitlesIdFieldFallback:
    """Tests for the multi-field id fallback (pg_id -> id)."""

    @pytest.mark.asyncio
    async def test_default_id_fields_prefers_pg_id_over_id(self) -> None:
        """Default (pg_id, id) fallback: pg_id is preferred when present."""
        articles = [
            {"pg_id": "FROM_PG", "id": "FROM_ID"},  # should pick pg_id
            {"id": "ONLY_ID"},  # should fall back to id
        ]

        repo = MagicMock()
        repo.fetch_titles_by_pg_ids = AsyncMock(return_value={})

        pg_ids = await enrich_articles_with_titles(articles, article_repo=repo)

        assert pg_ids == ["from_pg", "only_id"]

    @pytest.mark.asyncio
    async def test_custom_id_fields_single_key(self) -> None:
        """Caller can restrict to a single key (e.g. Neo4j only has 'id')."""
        articles = [{"id": "abc"}, {"pg_id": "xyz"}]

        repo = MagicMock()
        repo.fetch_titles_by_pg_ids = AsyncMock(return_value={})

        pg_ids = await enrich_articles_with_titles(articles, article_repo=repo, id_fields=["id"])

        # Only the article with "id" is picked up; "pg_id" is ignored.
        assert pg_ids == ["abc"]

    @pytest.mark.asyncio
    async def test_falsy_id_values_are_skipped(self) -> None:
        """Empty strings, None, 0 are skipped (not coerced to 'None' str)."""
        articles = [
            {"id": ""},  # empty string
            {"id": None},  # None
            {"id": "valid"},  # valid
        ]

        repo = MagicMock()
        repo.fetch_titles_by_pg_ids = AsyncMock(return_value={})

        pg_ids = await enrich_articles_with_titles(articles, article_repo=repo)

        assert pg_ids == ["valid"]


class TestEnrichArticlesWithTitlesErrorHandling:
    """Tests for fetch_titles_by_pg_ids raising exceptions."""

    @pytest.mark.asyncio
    async def test_fetch_raises_falls_back_to_defaults(self) -> None:
        """When fetch raises, articles get defaults and pg_ids are still returned.

        Rule 12: failures must be explicit (logged) but must not silently
        abort partial success — we keep the pg_ids list so the caller can
        still attempt body fetching.
        """
        articles = [{"id": "a"}, {"id": "b"}]

        repo = MagicMock()
        repo.fetch_titles_by_pg_ids = AsyncMock(side_effect=Exception("DB down"))

        pg_ids = await enrich_articles_with_titles(articles, article_repo=repo)

        # pg_ids still returned for caller's body-fetch step.
        assert pg_ids == ["a", "b"]
        # Defaults applied (graceful degradation).
        assert all(a["title"] == "" for a in articles)

    @pytest.mark.asyncio
    async def test_fetch_raises_does_not_overwrite_existing_title(self) -> None:
        """setdefault semantics: failure path must not overwrite pre-existing title."""
        articles = [{"id": "a", "title": "Pre-existing"}]

        repo = MagicMock()
        repo.fetch_titles_by_pg_ids = AsyncMock(side_effect=RuntimeError("boom"))

        await enrich_articles_with_titles(articles, article_repo=repo)

        assert articles[0]["title"] == "Pre-existing"


class TestEnrichArticlesWithTitlesReturnContract:
    """Verify the returned pg_ids list contract."""

    @pytest.mark.asyncio
    async def test_pg_ids_are_lowercased_to_match_fetch_titles_contract(self) -> None:
        """fetch_titles_by_pg_ids returns lowercase UUID-string keys; the
        returned pg_ids must match this convention so callers can use them
        directly with fetch_bodies_by_pg_ids.
        """
        # Simulate UUID strings with mixed case.
        articles = [{"id": "AAA-BBB-CCC"}, {"id": "DdEeFf"}]

        repo = MagicMock()
        repo.fetch_titles_by_pg_ids = AsyncMock(return_value={})

        pg_ids = await enrich_articles_with_titles(articles, article_repo=repo)

        assert pg_ids == ["aaa-bbb-ccc", "ddeeff"]
        # fetch_titles called with the same lowercase list (single batch).
        repo.fetch_titles_by_pg_ids.assert_awaited_once_with(["aaa-bbb-ccc", "ddeeff"])

    @pytest.mark.asyncio
    async def test_caller_can_reuse_pg_ids_for_body_fetch(self) -> None:
        """Integration-style: returned pg_ids plug into fetch_bodies_by_pg_ids."""
        articles = [{"id": "abc"}, {"id": "def"}]

        repo = MagicMock()
        repo.fetch_titles_by_pg_ids = AsyncMock(return_value={})
        repo.fetch_bodies_by_pg_ids = AsyncMock(return_value={"abc": "body-A", "def": "body-B"})

        pg_ids = await enrich_articles_with_titles(articles, article_repo=repo)

        # Caller reuses pg_ids for body fetch — exactly the pattern that
        # local_context.py / ladybug_local_context.py use.
        bodies = await repo.fetch_bodies_by_pg_ids(pg_ids)
        assert bodies["abc"] == "body-A"
