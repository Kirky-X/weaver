# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Shared article-enrichment helper used by graph-query context builders.

After the Article node slim-down (design.md §D2), the graph DB Article
node stores only ``pg_id``. Graph-query callers (``LocalContextBuilder``,
``LadybugLocalContextBuilder``) need to batch-fetch business fields
(``title`` / ``category`` / ``publish_time`` / ``score``) from the
relational DB and merge them into the article dicts returned by the
graph query.

Previously each builder inlined ~27 lines of identical title-enrichment
logic. This module extracts that shared logic into
``enrich_articles_with_titles`` so both builders stay in sync.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from core.observability import get_logger

if TYPE_CHECKING:
    from core.protocols import ArticleRepository

log = get_logger(__name__)

# Default ordered fallback of dict keys to try as the article's pg_id.
# ``pg_id`` is the canonical key after the slim-down (design.md §D2);
# ``id`` is the legacy key still produced by Neo4j queries that select
# ``a.pg_id AS id``. Both are tried in order so a single default works
# for both Neo4j and LadybugDB callers.
_DEFAULT_ID_FIELDS: tuple[str, ...] = ("pg_id", "id")


def _extract_pg_id(article: dict[str, Any], id_fields: tuple[str, ...]) -> str | None:
    """Return the first non-falsy pg_id found in ``article`` via ``id_fields``.

    Returns the lowercased string form, or ``None`` when no key yields a
    truthy value. Empty strings and ``None`` are treated as missing.
    """
    for key in id_fields:
        value = article.get(key)
        if value:
            return str(value).lower()
    return None


async def enrich_articles_with_titles(
    articles: list[dict[str, Any]],
    article_repo: ArticleRepository | None,
    id_fields: Sequence[str] | None = None,
) -> list[str]:
    """Batch-enrich article dicts with title/category/publish_time/score.

    Mutates each article dict in place by setting ``title`` /
    ``publish_time`` / ``category`` / ``score`` from a single
    ``ArticleRepository.fetch_titles_by_pg_ids`` call. Articles whose
    pg_id is not found in PG get ``title=""`` and ``publish_time=None``
    via ``setdefault`` (graceful degradation that preserves any
    pre-existing values).

    Args:
        articles: List of article dicts to enrich (mutated in place).
            Each dict is expected to carry a ``pg_id`` or ``id`` field
            (tried in order — see ``id_fields``).
        article_repo: ``ArticleRepository`` instance, or ``None`` for
            degraded mode (skips the DB call and just applies defaults).
        id_fields: Ordered iterable of dict keys to try as the pg_id
            source. Defaults to ``("pg_id", "id")``. Pass ``["id"]``
            when only the ``id`` key is meaningful (Neo4j path).

    Returns:
        List of valid pg_ids (lowercase strings) extracted from
        ``articles`` in input order. Callers reuse this list to batch
        fetch article bodies via ``fetch_bodies_by_pg_ids`` — see
        ``ContextBuilder.fetch_article_bodies``.

    Failure modes (rule 12: failures must be explicit):
        - ``fetch_titles_by_pg_ids`` raises: caught, logged with
          ``pg_id_count`` context, and articles fall back to defaults.
          The pg_ids list is still returned so callers can attempt
          body fetching (which may succeed even if title lookup failed).
    """
    fields = tuple(id_fields) if id_fields is not None else _DEFAULT_ID_FIELDS

    # Stage 1: extract pg_ids from articles in input order.
    pg_ids: list[str] = []
    for article in articles:
        pg_id = _extract_pg_id(article, fields)
        if pg_id is not None:
            pg_ids.append(pg_id)

    # Stage 2: batch-fetch titles from PG (when repo + pg_ids available).
    titles: dict[str, Any] = {}
    if article_repo is not None and pg_ids:
        try:
            titles = await article_repo.fetch_titles_by_pg_ids(pg_ids)
        except Exception as exc:
            log.warning(
                "enrich_articles_with_titles_failed",
                error=str(exc),
                pg_id_count=len(pg_ids),
            )
            titles = {}

    # Stage 3: merge metadata into each article dict (in place).
    for article in articles:
        pg_id = _extract_pg_id(article, fields)
        meta = titles.get(pg_id) if pg_id else None
        if meta:
            # All four fields overwritten with real values from PG.
            # ``None`` values from meta (terminal/legacy articles) are
            # propagated intentionally — caller can distinguish "found
            # but terminal" from "not found at all".
            article["title"] = meta.get("title", "")
            article["publish_time"] = meta.get("publish_time")
            article["category"] = meta.get("category")
            article["score"] = meta.get("score")
        else:
            # Graceful degradation: only set title/publish_time defaults
            # (matches legacy behaviour — category/score left untouched).
            # setdefault preserves any pre-existing values.
            article.setdefault("title", "")
            article.setdefault("publish_time", None)

    return pg_ids
