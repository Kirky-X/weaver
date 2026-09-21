# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Article repository for PostgreSQL CRUD operations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, bindparam, func, select

from core.db import (
    Article,
    ArticleBody,
    ArticleCore,
    ArticleProcessing,
    PersistStatus,
)
from core.observability import get_logger
from core.protocols import RelationalPool
from core.types.ingestion_models import RawArticle
from core.url_utils import normalize_url

if TYPE_CHECKING:
    from core.protocols.types import ArticleTitleMeta

log = get_logger(__name__)

# Lazy spaCy handle for CJK query tokenization (loaded on first use, never at
# import time). Without it a Chinese query would be one indivisible LIKE term.
_nlp_cache: dict[str, Any] = {}


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _split_query_terms(query: str) -> list[str]:
    """Split a search query into AND-combinable LIKE terms.

    ASCII words pass through as-is. CJK runs longer than two characters are
    segmented with the spaCy zh model when available — an unsegmented Chinese
    sentence as a single ``CONTAINS`` term matches essentially nothing. When
    the model is unavailable the run stays whole, which degrades to the
    legacy behaviour instead of failing.
    """
    terms: list[str] = []
    for raw in query.split():
        if not raw:
            continue
        if not _has_cjk(raw) or len(raw) <= 2:
            terms.append(raw.lower())
            continue

        segmented = _segment_cjk(raw)
        terms.extend(t.lower() for t in segmented if t.strip())

    # De-duplicate while preserving order
    seen: set[str] = set()
    return [t for t in terms if not (t in seen or seen.add(t))]


def _segment_cjk(text: str) -> list[str]:
    """Segment a CJK run with spaCy zh, falling back to the whole run."""
    nlp = _nlp_cache.get("zh")
    if nlp is None and not _nlp_cache:
        try:
            import spacy as _spacy

            nlp = _spacy.load("zh_core_web_lg", disable=["ner", "parser", "lemmatizer"])
            _nlp_cache["zh"] = nlp
        except Exception as exc:
            log.debug("cjk_query_segmentation_model_unavailable", error=str(exc))
            _nlp_cache["unavailable"] = True
            return [text]
    elif nlp is None:
        return [text]

    doc = nlp(text)
    return [token.text for token in doc if not token.is_space and not token.is_punct] or [text]


class ArticleRepo:
    """PostgreSQL article repository.

    Handles article CRUD, persist status management,
    and URL dedup queries.

    Implements:
        - ArticleRepository: Article persistence and retrieval operations

    Args:
        pool: Relational database connection pool (PostgreSQL or DuckDB).
    """


class ArticleReader:
    """ArticleReader half of the ArticleRepo split."""

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    async def get(self, article_id: str | uuid.UUID) -> Article | None:
        """Get an article by ID."""
        if isinstance(article_id, str):
            article_id = uuid.UUID(article_id)
        async with self._pool.session() as session:
            result = await session.execute(select(Article).where(Article.id == article_id))
            return result.scalar_one_or_none()

    async def get_by_id(self, article_id: str | uuid.UUID) -> Article | None:
        """Get an article by ID (alias for get).

        Args:
            article_id: The article UUID or string.

        Returns:
            Article instance or None if not found.
        """
        return await self.get(article_id)

    async def get_by_ids(self, ids: list[str]) -> list[RawArticle]:
        """Fetch RawArticle objects by IDs for queue consumer.

        Args:
            ids: List of article UUID strings.

        Returns:
            List of RawArticle objects.
        """
        if not ids:
            return []

        async with self._pool.session() as session:
            uuid_ids = [uuid.UUID(id) for id in ids]
            query = select(Article).where(Article.id.in_(uuid_ids))
            result = await session.execute(query)
            articles = result.scalars().all()

            raw_articles = []
            for a in articles:
                raw = RawArticle(
                    url=a.source_url,
                    title=a.title or "",
                    body=a.body or "",
                    source=a.source_host or "",
                    source_host=a.source_host or "",
                    source_id=a.source_id,
                    publish_time=a.publish_time,
                )
                raw_articles.append(raw)

            return raw_articles

    async def get_existing_urls(self, urls: list[str]) -> set[str]:
        """Check which URLs already exist in the database.

        Queries ArticleCore (actual table) rather than the Article VIEW
        for reliable existence checks.

        Args:
            urls: List of URLs to check.

        Returns:
            Set of URLs that exist in the database.
        """
        if not urls:
            return set()

        normalized_urls = [normalize_url(u) for u in urls]
        # Chunk large inputs: same 500-item expanding-bindparam
        # strategy as fetch_titles_by_pg_ids — avoids PG parameter limits
        # and plan-cache bloat from a single giant IN clause.
        CHUNK_SIZE = 500
        found: set[str] = set()
        async with self._pool.session() as session:
            for i in range(0, len(normalized_urls), CHUNK_SIZE):
                chunk = normalized_urls[i : i + CHUNK_SIZE]
                result = await session.execute(
                    select(ArticleCore.source_url).where(
                        ArticleCore.source_url.in_(bindparam("urls", chunk, expanding=True))
                    )
                )
                found.update(row[0] for row in result)
            return found

    async def get_existing_titles(self, titles: set[str]) -> set[str]:
        """Check which titles already exist in the database (exact match).

        Safety-net dedup (Level 3) for when SimHash fingerprints are missing.

        Args:
            titles: Set of titles to check.

        Returns:
            Set of titles that already exist.
        """
        if not titles:
            return set()

        async with self._pool.session() as session:
            result = await session.execute(
                select(ArticleCore.title).where(ArticleCore.title.in_(titles))
            )
            return {row[0] for row in result if row[0]}

    async def get_pending(self, limit: int = 50) -> list[Article]:
        """Get articles with persist_status='PENDING' for processing.

        Args:
            limit: Maximum number of articles to return.

        Returns:
            List of pending articles.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(Article)
                .where(Article.persist_status == PersistStatus.PENDING)
                .order_by(Article.created_at.asc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_pending_neo4j(self, limit: int = 50) -> list[Article]:
        """Get articles with persist_status='pg_done' for Neo4j retry."""
        async with self._pool.session() as session:
            result = await session.execute(
                select(Article)
                .where(Article.persist_status == PersistStatus.PG_DONE)
                .order_by(Article.updated_at.asc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_stuck_articles(self, timeout_minutes: int = 30) -> list[Article]:
        """Get articles stuck in PROCESSING state beyond timeout.

        These are articles that were being processed but the pipeline
        was interrupted before completion.

        Args:
            timeout_minutes: Minutes after which an article is considered stuck.

        Returns:
            List of stuck articles.
        """
        threshold = datetime.now(UTC) - timedelta(minutes=timeout_minutes)

        async with self._pool.session() as session:
            result = await session.execute(
                select(Article)
                .where(
                    and_(
                        Article.persist_status == PersistStatus.PROCESSING,
                        Article.updated_at < threshold,
                    )
                )
                .limit(50)
            )
            return list(result.scalars().all())

    # Full-table ID loads are inherently unbounded; log when the result set
    # grows past this so operators notice before memory becomes a problem.
    ALL_IDS_WARN_THRESHOLD = 500_000

    async def get_all_article_ids(self) -> set[str]:
        """Get all article IDs from PostgreSQL.

        Deliberately unbounded: callers (orphan cleanup, consistency jobs)
        need the complete ID set for set-difference checks — a LIMIT would
        break correctness. A guard log fires when the set exceeds
        ``ALL_IDS_WARN_THRESHOLD`` rows.

        Returns:
            Set of article ID strings.
        """
        async with self._pool.session() as session:
            result = await session.execute(select(ArticleCore.id))
            ids = {str(row[0]) for row in result}

        if len(ids) > self.ALL_IDS_WARN_THRESHOLD:
            log.warning(
                "get_all_article_ids_large_result",
                count=len(ids),
                threshold=self.ALL_IDS_WARN_THRESHOLD,
            )
        return ids

    async def get_incomplete_articles(self, limit: int = 50) -> list[Article]:
        """Get articles with neo4j_done status but missing enrichment data.

        An article is considered incomplete if ANY of the enrichment fields
        (category, score, credibility_score, summary, quality_score) is NULL.
        This ensures articles with partial enrichment are detected and retried.

        Args:
            limit: Maximum number of articles to return.

        Returns:
            List of incomplete articles.
        """
        from sqlalchemy import or_

        async with self._pool.session() as session:
            result = await session.execute(
                select(Article)
                .where(
                    and_(
                        Article.persist_status.in_(PersistStatus.completed_statuses()),
                        or_(
                            Article.category.is_(None),
                            Article.score.is_(None),
                            Article.credibility_score.is_(None),
                            Article.summary.is_(None),
                            Article.quality_score.is_(None),
                        ),
                    )
                )
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_failed_articles(self, max_retries: int = 3) -> list[Article]:
        """Get failed articles that are eligible for retry.

        Args:
            max_retries: Maximum retry count to consider for retry.

        Returns:
            List of failed articles that can be retried.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(Article)
                .where(
                    and_(
                        Article.persist_status == PersistStatus.FAILED,
                        Article.retry_count < max_retries,
                    )
                )
                .limit(50)
            )
            return list(result.scalars().all())

    async def fetch_titles_by_pg_ids(
        self,
        pg_ids: list[str],
    ) -> dict[str, ArticleTitleMeta]:
        """Batch fetch article metadata by PostgreSQL IDs.

        Used by graph-query callers that, after the Article node slim-down, can only read ``pg_id`` from the graph DB and must
        look up ``title`` / ``category`` / ``publish_time`` / ``score`` from
        the relational DB in a single batched query (avoids N+1).

        Implements:
            - ArticleRepository.fetch_titles_by_pg_ids

        .. warning::
            Do NOT call this method inside a per-article loop — that
            defeats the N+1 avoidance. Pass the full ``pg_ids`` list in
            one shot.

        Args:
            pg_ids: List of article UUID strings. Empty list short-circuits
                without opening a session. Invalid UUID strings are skipped
                with a warning log (not raised). Mapping keys are lowercase
                UUID strings — callers querying the result must use
                ``pg_id.lower()`` to look up entries.

        Returns:
            Mapping of ``pg_id`` (lowercase UUID string) -> ``ArticleTitleMeta``.
            Missing IDs are omitted from the result. ``publish_time`` /
            ``score`` may be ``None`` for terminal or legacy articles.
        """
        if not pg_ids:
            return {}

        # Filter out invalid UUIDs (graph DB may carry historical dirty
        # data; one bad pg_id must not abort the entire batch — rule 12
        # "failures must be explicit"). Aggregate to a single warning log
        # with a 5-item sample to avoid log spam when many pg_ids are dirty.
        uuid_ids: list[uuid.UUID] = []
        skipped: list[str] = []
        for pid in pg_ids:
            try:
                uuid_ids.append(uuid.UUID(pid))
            except (ValueError, AttributeError, TypeError):
                skipped.append(pid)
        if skipped:
            log.warning(
                "fetch_titles_by_pg_ids_invalid_skipped",
                skipped_count=len(skipped),
                total_count=len(pg_ids),
                sample=skipped[:5],
            )
        if not uuid_ids:
            return {}

        # Chunk to avoid PG parameter limits (soft limit 65535) and DuckDB
        # plan-cache bloat. 500 keeps parse time <10ms while limiting round
        # trips to ~100 for 50K pg_ids (realistic max). Reads can use a
        # larger chunk than writes (bulk_upsert uses 50) since no
        # transaction lock is held.
        CHUNK_SIZE = 500
        mapping: dict[str, ArticleTitleMeta] = {}
        # Single shared session for all chunks — read-only queries have no
        # transaction isolation needs, unlike bulk_upsert's per-state session
        # for failure isolation. Avoids N session-construction overheads.
        async with self._pool.session() as session:
            for i in range(0, len(uuid_ids), CHUNK_SIZE):
                chunk = uuid_ids[i : i + CHUNK_SIZE]
                # expanding bindparam lets PG reuse a single plan across
                # chunks of identical size (avoids plan-cache bloat).
                stmt = select(
                    ArticleCore.id,
                    ArticleCore.title,
                    ArticleCore.category,
                    ArticleCore.publish_time,
                    ArticleCore.score,
                ).where(ArticleCore.id.in_(bindparam("ids", chunk, expanding=True)))
                result = await session.execute(stmt)
                # NOTE: row[i] indices match SELECT column order above —
                # keep in sync if reordering columns.
                for row in list(result):
                    pid_str = str(row[0])
                    mapping[pid_str] = {
                        "title": row[1],
                        "category": row[2],
                        "publish_time": row[3],
                        "score": row[4],
                    }
        log.debug(
            "fetch_titles_by_pg_ids_complete",
            requested=len(pg_ids),
            returned=len(mapping),
            skipped=len(skipped),
        )
        return mapping

    async def fetch_bodies_by_pg_ids(
        self,
        pg_ids: list[str],
    ) -> dict[str, str]:
        """Batch fetch article body content by PostgreSQL IDs.

        Mirrors ``fetch_titles_by_pg_ids`` but selects ``body`` from
        ``article_bodies`` instead of metadata columns. Used by
        ``ContextBuilder.fetch_article_bodies`` to replace the per-id
        ``repo.get`` N+1 loop with a single batched SELECT.

        Implements:
            - ArticleRepository.fetch_bodies_by_pg_ids

        .. warning::
            Do NOT call this method inside a per-article loop — that
            defeats the N+1 avoidance. Pass the full ``pg_ids`` list in
            one shot.

        Args:
            pg_ids: List of article UUID strings. Empty list short-circuits
                without opening a session. Invalid UUID strings are skipped
                with a warning log (not raised). Mapping keys are lowercase
                UUID strings — callers querying the result must use
                ``pg_id.lower()`` to look up entries.

        Returns:
            Mapping of ``pg_id`` (lowercase UUID string) -> body text.
            Missing IDs are omitted from the result (not empty string).
        """
        if not pg_ids:
            return {}

        # Filter out invalid UUIDs (graph DB may carry historical dirty data;
        # one bad pg_id must not abort the entire batch — rule 12). Aggregate
        # to a single warning log with a 5-item sample to avoid log spam.
        uuid_ids: list[uuid.UUID] = []
        skipped: list[str] = []
        for pid in pg_ids:
            try:
                uuid_ids.append(uuid.UUID(pid))
            except (ValueError, AttributeError, TypeError):
                skipped.append(pid)
        if skipped:
            log.warning(
                "fetch_bodies_by_pg_ids_invalid_skipped",
                skipped_count=len(skipped),
                total_count=len(pg_ids),
                sample=skipped[:5],
            )
        if not uuid_ids:
            return {}

        # Chunk to avoid PG parameter limits (soft limit 65535) and DuckDB
        # plan-cache bloat. 500 keeps parse time <10ms while limiting round
        # trips. Reads can use a larger chunk than writes (no transaction
        # lock held).
        CHUNK_SIZE = 500
        mapping: dict[str, str] = {}
        # Single shared session for all chunks — read-only queries have no
        # transaction isolation needs. Avoids N session-construction overheads.
        async with self._pool.session() as session:
            for i in range(0, len(uuid_ids), CHUNK_SIZE):
                chunk = uuid_ids[i : i + CHUNK_SIZE]
                stmt = select(ArticleBody.article_id, ArticleBody.body).where(
                    ArticleBody.article_id.in_(bindparam("ids", chunk, expanding=True))
                )
                result = await session.execute(stmt)
                # row[0] is article_id (UUID); row[1] is body (Text).
                for row in list(result):
                    mapping[str(row[0])] = row[1]
        log.debug(
            "fetch_bodies_by_pg_ids_complete",
            requested=len(pg_ids),
            returned=len(mapping),
            skipped=len(skipped),
        )
        return mapping

    async def get_task_progress_stats(self, task_id: uuid.UUID) -> dict[str, int]:
        """Get progress statistics for a specific task.

        Queries ArticleProcessing for task_id and JOINs ArticleCore
        for persist_status distribution.

        Args:
            task_id: The task UUID to query.

        Returns:
            Dictionary with total_processed, processing_count, completed_count,
            failed_count, pending_count.
        """
        from sqlalchemy import case as sql_case, func

        async with self._pool.session() as session:
            result = await session.execute(
                select(
                    func.count(ArticleProcessing.article_id).label("total_processed"),
                    func.sum(
                        sql_case(
                            (ArticleCore.persist_status == PersistStatus.PROCESSING, 1), else_=0
                        )
                    ).label("processing_count"),
                    func.sum(
                        sql_case(
                            (
                                ArticleCore.persist_status.in_(
                                    list(PersistStatus.completed_statuses())
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ).label("completed_count"),
                    func.sum(
                        sql_case((ArticleCore.persist_status == PersistStatus.FAILED, 1), else_=0)
                    ).label("failed_count"),
                    func.sum(
                        sql_case((ArticleCore.persist_status == PersistStatus.PENDING, 1), else_=0)
                    ).label("pending_count"),
                )
                .join(ArticleCore, ArticleCore.id == ArticleProcessing.article_id)
                .where(ArticleProcessing.task_id == task_id)
            )
            row = result.one()
            return {
                "total_processed": row.total_processed or 0,
                "processing_count": int(row.processing_count or 0),
                "completed_count": int(row.completed_count or 0),
                "failed_count": int(row.failed_count or 0),
                "pending_count": int(row.pending_count or 0),
            }

    async def search_by_text(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search articles whose title or body contains the query terms.

        This is a fallback search when graph-based entity search returns
        no results. Terms are combined with AND; CJK runs are segmented
        via the spaCy zh model (lazy) so natural-language Chinese queries
        match — an unsegmented sentence as a single ``contains()`` term
        matches essentially nothing. Uses ``func.lower().contains()`` for
        case-insensitive matching (DuckDB compatible; ILIKE may not work
        in DuckDB).

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            List of article dicts with id, title, body_excerpt, source_url,
            source_host, summary, publish_time.
        """
        if not query or not query.strip():
            return []

        query_terms = _split_query_terms(query.strip())
        if not query_terms:
            return []

        async with self._pool.session() as session:
            # Search by title first (higher priority), then by body.
            # Use func.lower().contains() for DuckDB compatibility.
            term_predicates = [
                func.lower(Article.title).contains(term) | func.lower(Article.body).contains(term)
                for term in query_terms
            ]
            stmt = (
                select(
                    Article.id,
                    Article.title,
                    Article.body,
                    Article.source_url,
                    Article.source_host,
                    Article.summary,
                    Article.publish_time,
                )
                .where(and_(*term_predicates))
                .order_by(Article.publish_time.desc())
                .limit(limit)
            )

            try:
                result = await session.execute(stmt)
                rows = result.all()
            except Exception as exc:
                log.warning("search_by_text_failed", error=str(exc), query=query)
                return []

            articles: list[dict[str, Any]] = []
            for row in rows:
                body_text = row.body or ""
                # Excerpt around the first matching term (whole-sentence
                # positions rarely exist in segmented CJK queries).
                excerpt = ""
                for term in query_terms:
                    excerpt = self._extract_excerpt(body_text, term, max_chars=300)
                    if excerpt:
                        break
                articles.append(
                    {
                        "id": str(row.id),
                        "title": row.title,
                        "body_excerpt": excerpt,
                        "source_url": row.source_url,
                        "source_host": row.source_host,
                        "summary": row.summary,
                        "publish_time": row.publish_time.isoformat() if row.publish_time else None,
                    }
                )

            if articles:
                log.info(
                    "search_by_text_found",
                    count=len(articles),
                    query=query,
                )
            return articles

    @staticmethod
    def _extract_excerpt(
        body: str,
        query_lower: str,
        max_chars: int = 300,
    ) -> str:
        """Extract a relevant excerpt from article body around the query match.

        Args:
            body: Article body text.
            query_lower: Lowercased query string.
            max_chars: Maximum excerpt length.

        Returns:
            Excerpt string with ellipsis if truncated.
        """
        if not body:
            return ""

        body_lower = body.lower()
        pos = body_lower.find(query_lower)
        if pos == -1:
            # Try word-by-word matching for multi-word queries
            words = query_lower.split()
            for word in words:
                if len(word) >= 2:
                    pos = body_lower.find(word)
                    if pos != -1:
                        break

        if pos == -1:
            # No match found, return beginning
            return body[:max_chars] + ("..." if len(body) > max_chars else "")

        # Extract context around the match
        start = max(0, pos - max_chars // 3)
        end = min(len(body), start + max_chars)
        excerpt = body[start:end]
        if start > 0:
            excerpt = "..." + excerpt
        if end < len(body):
            excerpt = excerpt + "..."
        return excerpt

    async def detect_merge_cycle(
        self, article_id: uuid.UUID, target_id: uuid.UUID
    ) -> list[uuid.UUID] | None:
        """Detect if setting merged_to target would create a cycle.

        Uses PostgreSQL recursive CTE to trace the merged_into chain efficiently.

        Args:
            article_id: The source article that would be merged.
            target_id: The target article to merge into.

        Returns:
            List of IDs forming the cycle if detected, None otherwise.
        """
        if article_id == target_id:
            return [article_id, target_id]

        from sqlalchemy import text

        async with self._pool.session() as session:
            # Use recursive CTE to get entire merge chain in single query.
            # array_append(mc.path, a.id) instead of `mc.path || a.id`:
            # DuckDB rejects UUID[] || UUID without an explicit cast, while
            # array_append works on both PostgreSQL and DuckDB.
            result = await session.execute(
                text("""
                     WITH RECURSIVE merge_chain AS (SELECT id, merged_into, ARRAY[id] as path, false as cycle
                                                    FROM articles_core
                                                    WHERE id = :target_id

                                                    UNION ALL

                                                    SELECT a.id, a.merged_into, array_append(mc.path, a.id), a.id = ANY (mc.path)
                                                    FROM articles_core a
                                                             INNER JOIN merge_chain mc ON a.id = mc.merged_into
                                                    WHERE NOT mc.cycle)
                     SELECT id, path, cycle
                     FROM merge_chain
                     """),
                {"target_id": str(target_id)},
            )

            rows = result.all()
            for row in rows:
                if row.cycle:
                    cycle_path = row.path
                    log.warning(
                        "merge_cycle_detected",
                        source_id=str(article_id),
                        target_id=str(target_id),
                        cycle=cycle_path,
                    )
                    return cycle_path

            # Check if article_id appears in the chain
            for row in rows:
                if article_id in row.path:
                    cycle_path = row.path + [article_id]
                    log.warning(
                        "merge_cycle_detected",
                        source_id=str(article_id),
                        target_id=str(target_id),
                        cycle=cycle_path,
                    )
                    return cycle_path

        return None

    async def resolve_final_merge_target(self, article_id: uuid.UUID) -> uuid.UUID | None:
        """Resolve the final target of a merge chain.

        Follows the merged_into chain to the end, detecting cycles. Uses a
        single recursive CTE (same pattern as ``detect_merge_cycle``)
        instead of one SELECT per hop (N+1 queries).

        Args:
            article_id: The article to resolve.

        Returns:
            The final target ID, or None if no merge or a cycle was found.
        """
        from sqlalchemy import text

        async with self._pool.session() as session:
            # array_append(mc.path, a.id) instead of `mc.path || a.id`:
            # DuckDB rejects UUID[] || UUID without an explicit cast, while
            # array_append works on both PostgreSQL and DuckDB.
            result = await session.execute(
                text("""
                     WITH RECURSIVE merge_chain AS (SELECT id, merged_into, ARRAY[id] as path
                                                    FROM articles_core
                                                    WHERE id = :article_id

                                                    UNION ALL

                                                    SELECT a.id, a.merged_into, array_append(mc.path, a.id)
                                                    FROM articles_core a
                                                             INNER JOIN merge_chain mc ON a.id = mc.merged_into
                                                    WHERE NOT (a.id = ANY (mc.path)))
                     SELECT id, merged_into, path
                     FROM merge_chain
                     """),
                {"article_id": str(article_id)},
            )

            rows = result.all()
            if not rows:
                return None

            # The terminal row carries the longest path (chain start → end)
            terminal = max(rows, key=lambda r: len(r.path))

            if terminal.merged_into is not None and terminal.merged_into in terminal.path:
                log.error(
                    "merge_cycle_in_chain",
                    article_id=str(article_id),
                    cycle_at=str(terminal.id),
                )
                return None

            return terminal.path[-1]
