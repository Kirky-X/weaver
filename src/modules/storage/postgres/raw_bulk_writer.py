# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Article repository for PostgreSQL CRUD operations."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from core.change_detector import ChangeDetector
from core.db import (
    ArticleAnalysis,
    ArticleBody,
    ArticleCore,
    ArticleProcessing,
    PersistStatus,
)
from core.observability import get_logger
from core.protocols import RelationalPool
from core.url_utils import normalize_url

if TYPE_CHECKING:
    pass

log = get_logger(__name__)

# Minimum body length to consider a fetch successful (vs anti-bot error page)
_MIN_BODY_LENGTH = 200


def _build_core_body_values(
    raw: Any,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Build ArticleCore / ArticleBody kwargs + body_source for a RawArticle.

    Shared by ``insert_raw`` and ``bulk_insert_raw`` to keep body-length
    fallback, normalization, and content-hash logic in one place.

    Args:
        raw: RawArticle with non-empty url.

    Returns:
        Tuple of (core_kwargs, body_kwargs, body_source) where body_source
        is "full" or "description" (the latter when raw.body < _MIN_BODY_LENGTH
        and a description fallback is available).
    """
    effective_body = raw.body
    body_source = "full"
    if len(effective_body) < _MIN_BODY_LENGTH and raw.description:
        effective_body = raw.description
        body_source = "description"
        log.info(
            "body_too_short_using_description",
            url=raw.url,
            body_len=len(raw.body),
            desc_len=len(raw.description),
        )

    normalized_url = normalize_url(raw.url)
    content_hash = ChangeDetector.compute_hash({"title": raw.title or "", "body": effective_body})

    core_kwargs: dict[str, Any] = {
        "source_url": normalized_url,
        "source_host": raw.source_host or "",
        "source_id": raw.source_id,
        "title": raw.title or "",
        "persist_status": PersistStatus.PENDING,
        "content_hash": content_hash,
    }
    if raw.publish_time:
        core_kwargs["publish_time"] = raw.publish_time

    body_kwargs: dict[str, Any] = {"body": effective_body}
    return core_kwargs, body_kwargs, body_source


class ArticleRepo:
    """PostgreSQL article repository.

    Handles article CRUD, persist status management,
    and URL dedup queries.

    Implements:
        - ArticleRepository: Article persistence and retrieval operations

    Args:
        pool: Relational database connection pool (PostgreSQL or DuckDB).
    """



class RawBulkWriter:
    """RawBulkWriter half of the ArticleRepo split (T022)."""

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    async def insert_raw(self, article: Any, task_id: uuid.UUID | None = None) -> uuid.UUID:
        """Insert a raw article directly into the database.

        This is used for initial insertion of crawled articles before
        they are processed through the pipeline. Inserts into ArticleCore
        and ArticleBody (split tables), not the Article VIEW.

        Args:
            article: Raw article data from crawler (RawArticle or NewsItem).
            task_id: Optional task ID for tracking the source pipeline run.

        Returns:
            The article UUID.
        """
        from core.types.ingestion_models import NewsItem, RawArticle

        # Convert if needed
        if isinstance(article, RawArticle):
            raw = article
        elif isinstance(article, NewsItem):
            # Convert NewsItem to RawArticle format
            raw = RawArticle(
                url=article.url,
                title=article.title,
                body=article.description or "",
                source=article.source,
                publish_time=article.publish_time,
                source_host=article.source_host,
                description=article.description or "",
            )
        else:
            # Try to extract attributes from arbitrary object
            raw = RawArticle(
                url=getattr(article, "url", ""),
                title=getattr(article, "title", ""),
                body=getattr(article, "description", "") or getattr(article, "body", ""),
                source=getattr(article, "source", ""),
                publish_time=getattr(article, "publish_time", None),
                source_host=getattr(article, "source_host", ""),
                description=getattr(article, "description", ""),
            )

        if not raw.url:
            raise ValueError("Article URL is required")

        # Fall back to RSS description when body is too short (e.g. anti-bot error pages).
        # A typical article body is hundreds of characters; error pages are < 200 chars.
        MIN_BODY_LENGTH = 200
        effective_body = raw.body
        body_source = "full"
        if len(effective_body) < MIN_BODY_LENGTH and raw.description:
            effective_body = raw.description
            body_source = "description"
            log.info(
                "body_too_short_using_description",
                url=raw.url,
                body_len=len(raw.body),
                desc_len=len(raw.description),
            )

        normalized_url = normalize_url(raw.url)
        content_hash = ChangeDetector.compute_hash(
            {"title": raw.title or "", "body": effective_body}
        )

        async with self._pool.session() as session:
            # Check if exists using ArticleCore
            result = await session.execute(
                select(ArticleCore.id).where(ArticleCore.source_url == normalized_url)
            )
            existing_id = result.scalar_one_or_none()

            if existing_id:
                log.debug("article_already_exists", url=raw.url, normalized=normalized_url)
                return existing_id

            # Insert into articles_core
            core = ArticleCore(
                source_url=normalized_url,
                source_host=raw.source_host or "",
                source_id=raw.source_id,
                title=raw.title or "",
                persist_status=PersistStatus.PENDING,
                content_hash=content_hash,
            )
            if raw.publish_time:
                core.publish_time = raw.publish_time

            session.add(core)
            await session.flush()

            # Insert into article_processing (vertical split from core)
            processing = ArticleProcessing(
                article_id=core.id,
                task_id=task_id,
            )
            session.add(processing)

            # Insert into article_bodies
            body = ArticleBody(
                article_id=core.id,
                body=effective_body,
            )
            session.add(body)

            # Insert into article_analysis
            analysis_values = {"article_id": core.id, "is_news": True}
            prompt_versions = {"body_source": body_source} if body_source != "full" else None
            if prompt_versions:
                analysis_values["prompt_versions"] = prompt_versions
            analysis = ArticleAnalysis(**analysis_values)
            session.add(analysis)

            await session.commit()

            log.info("article_inserted", url=raw.url, article_id=str(core.id))
            return core.id

    async def bulk_insert_raw(
        self,
        articles: list[Any],
        task_id: uuid.UUID | None = None,
    ) -> list[uuid.UUID]:
        """Bulk insert raw articles with single commit and URL dedup (P0-2 fix).

        Replaces the N-call ``insert_raw`` for-loop in
        ``DiscoveryProcessor.on_items_discovered`` (170-176) to cut N
        session round-trips + N commits down to 1+1 per crawl batch.

        Pipeline:
            1. Normalize inputs to RawArticle (reject empty URL)
            2. Batch pre-query existing URLs via ``WHERE source_url = ANY(:urls)``
            3. Single ``session.add_all`` + single ``session.commit()``
            4. Fallback to per-article ``insert_raw`` on batch failure

        Args:
            articles: List of RawArticle / NewsItem / duck-typed objects.
            task_id: Optional task ID for tracking.

        Returns:
            List of article UUIDs in input order. Existing URLs return
            their existing id; failed inserts are skipped (logged).
        """
        if not articles:
            return []

        from core.types.ingestion_models import NewsItem, RawArticle

        # Stage 1: normalize all inputs to RawArticle + compute normalized_url
        prepared: list[tuple[int, RawArticle, str]] = []  # (orig_idx, raw, normalized_url)
        for idx, article in enumerate(articles):
            if isinstance(article, RawArticle):
                raw = article
            elif isinstance(article, NewsItem):
                raw = RawArticle(
                    url=article.url,
                    title=article.title,
                    body=article.description or "",
                    source=article.source,
                    publish_time=article.publish_time,
                    source_host=article.source_host,
                    description=article.description or "",
                )
            else:
                raw = RawArticle(
                    url=getattr(article, "url", ""),
                    title=getattr(article, "title", ""),
                    body=getattr(article, "description", "") or getattr(article, "body", ""),
                    source=getattr(article, "source", ""),
                    publish_time=getattr(article, "publish_time", None),
                    source_host=getattr(article, "source_host", ""),
                    description=getattr(article, "description", ""),
                )

            if not raw.url:
                log.warning("bulk_insert_raw_skipped_no_url", index=idx)
                continue

            prepared.append((idx, raw, normalize_url(raw.url)))

        if not prepared:
            return []

        # Result list: fill in input order
        results: list[uuid.UUID | None] = [None] * len(articles)

        try:
            async with self._pool.session() as session:
                # Stage 2: batch pre-query existing URLs
                urls_to_check = [norm_url for _, _, norm_url in prepared]
                existing_query = select(ArticleCore.source_url, ArticleCore.id).where(
                    ArticleCore.source_url.in_(urls_to_check)
                )
                existing_result = await session.execute(existing_query)
                existing_map: dict[str, uuid.UUID] = {
                    row[0]: row[1] for row in existing_result.all()
                }

                # Stage 2.5: batch pre-query existing content_hashes
                # Cross-source dedup — prevents same content with different
                # URLs from being stored twice. Catches cases where title
                # extraction failed (empty title) and SimHash/DB title dedup
                # both skipped the item.
                hash_to_raw: dict[str, tuple[int, Any, str]] = {}
                for idx, raw, norm_url in prepared:
                    if existing_map.get(norm_url) is not None:
                        continue
                    effective_body = raw.body
                    if len(effective_body) < _MIN_BODY_LENGTH and raw.description:
                        effective_body = raw.description
                    ch = ChangeDetector.compute_hash(
                        {"title": raw.title or "", "body": effective_body}
                    )
                    hash_to_raw[ch] = (idx, raw, norm_url)

                existing_hashes: set[str] = set()
                if hash_to_raw:
                    hash_query = select(ArticleCore.content_hash, ArticleCore.id).where(
                        ArticleCore.content_hash.in_(set(hash_to_raw.keys()))
                    )
                    hash_result = await session.execute(hash_query)
                    for row in hash_result.all():
                        existing_hashes.add(row[0])
                        # Map duplicate content to existing article id so
                        # downstream pipeline can skip reprocessing.
                        ch = row[0]
                        if ch in hash_to_raw:
                            idx, _, _ = hash_to_raw[ch]
                            results[idx] = row[1]

                    if existing_hashes:
                        log.info(
                            "bulk_insert_raw_content_hash_dup",
                            dup_count=len(existing_hashes),
                            total_checked=len(hash_to_raw),
                        )

                # Stage 3: build new objects for URLs not in existing_map
                new_objects: list[Any] = []
                # Track (orig_idx, core_ref) so we can read core.id after flush
                pending_cores: list[tuple[int, ArticleCore]] = []
                # Track in-batch content_hashes to dedup within the same batch
                in_batch_hashes: set[str] = set()

                for idx, raw, norm_url in prepared:
                    existing_id = existing_map.get(norm_url)
                    if existing_id is not None:
                        results[idx] = existing_id
                        log.debug("bulk_insert_raw_existing", url=raw.url, normalized=norm_url)
                        continue

                    # Skip if content_hash already exists (cross-source dup
                    # in DB, or within the same batch)
                    effective_body = raw.body
                    if len(effective_body) < _MIN_BODY_LENGTH and raw.description:
                        effective_body = raw.description
                    ch = ChangeDetector.compute_hash(
                        {"title": raw.title or "", "body": effective_body}
                    )
                    if ch in existing_hashes:
                        log.info(
                            "bulk_insert_raw_skipped_content_hash_dup",
                            url=raw.url,
                            content_hash=ch,
                        )
                        continue
                    if ch in in_batch_hashes:
                        log.info(
                            "bulk_insert_raw_skipped_in_batch_dup",
                            url=raw.url,
                            content_hash=ch,
                        )
                        continue

                    in_batch_hashes.add(ch)
                    core_kwargs, body_kwargs, body_source = _build_core_body_values(raw)
                    core = ArticleCore(**core_kwargs)
                    session.add(core)
                    pending_cores.append((idx, core))

                    new_objects.append(ArticleProcessing(article_id=core.id, task_id=task_id))
                    new_objects.append(ArticleBody(article_id=core.id, **body_kwargs))

                    analysis_values: dict[str, Any] = {"article_id": core.id, "is_news": True}
                    prompt_versions = (
                        {"body_source": body_source} if body_source != "full" else None
                    )
                    if prompt_versions:
                        analysis_values["prompt_versions"] = prompt_versions
                    new_objects.append(ArticleAnalysis(**analysis_values))

                if pending_cores:
                    # Flush to assign IDs to new ArticleCore objects
                    await session.flush()
                    for idx, core in pending_cores:
                        results[idx] = core.id

                    # add_all the dependent objects (referencing core.id)
                    session.add_all(new_objects)

                    # Single commit
                    await session.commit()

                    for idx, core in pending_cores:
                        log.info(
                            "bulk_insert_raw_inserted",
                            url=core.source_url,
                            article_id=str(core.id),
                        )

            # Fill any None (shouldn't happen, but be defensive)
            return [r for r in results if r is not None]

        except Exception as batch_exc:
            log.warning(
                "bulk_insert_raw_batch_failed_fallback",
                error=str(batch_exc),
                article_count=len(articles),
            )
            # Fallback: per-article insert_raw
            fallback_ids: list[uuid.UUID] = []
            for idx, raw, _norm_url in prepared:
                try:
                    aid = await self.insert_raw(raw, task_id=task_id)
                    fallback_ids.append(aid)
                except Exception as per_exc:
                    log.error(
                        "bulk_insert_raw_fallback_failed",
                        url=raw.url,
                        error=str(per_exc),
                    )
            return fallback_ids

