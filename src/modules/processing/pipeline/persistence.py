# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Pipeline persistence collaborator.

Handles writing processed articles to PostgreSQL (articles + vectors) and
to the graph store (Neo4j / LadybugDB), including terminal-state handling
and per-article fallback when batch writes fail.

Extracted from ``Pipeline`` to keep the orchestrator focused on flow control.
"""

from __future__ import annotations

import traceback
import uuid
from typing import TYPE_CHECKING, Any

from core.observability import get_logger
from modules.knowledge.graph.neo4j_writer import Neo4jWriteCircuitOpen
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.protocols import (
        ArticleRepository,
        GraphWriter,
        VectorRepository,
    )

log = get_logger(__name__)


class PipelinePersistence:
    """Persist pipeline states to relational and graph stores.

    Single responsibility: write processed articles and their vectors to
    PostgreSQL, then write graph nodes/relationships. Handles batch and
    per-article fallback paths, terminal-state marking, and failure
    accounting.

    Args:
        article_repo: Article repository (PG). May be None when PG is unavailable.
        vector_repo: Vector repository. May be None.
        graph_writer: Graph writer (Neo4j / LadybugDB). May be None.
        phase3_concurrency: Concurrency hint for graph batch writes.
    """

    def __init__(
        self,
        *,
        article_repo: ArticleRepository | None,
        vector_repo: VectorRepository | None,
        graph_writer: GraphWriter | None,
        phase3_concurrency: int,
        pending_sync_repo: Any | None = None,
    ) -> None:
        self._article_repo = article_repo
        self._vector_repo = vector_repo
        self._graph_writer = graph_writer
        self._phase3_concurrency = phase3_concurrency
        # Receives pending_sync rows when the graph write circuit is open
        self._pending_sync_repo = pending_sync_repo

    async def persist_batch(
        self,
        states: list[PipelineState],
        batch_total: int,
        batch_completed: int,
        batch_failed: int,
    ) -> tuple[int, int]:
        """Persist batch of articles to Postgres and Neo4j.

        Orchestrates terminal-state handling, PG persistence, and graph
        persistence. Sub-methods preserve the original transaction semantics.

        Args:
            states: List of pipeline states to persist.
            batch_total: Total articles in batch.
            batch_completed: Number of completed articles so far.
            batch_failed: Number of failed articles so far.

        Returns:
            Tuple of (batch_completed, batch_failed) with updated counts.
        """
        log.info("persist_batch_called", count=len(states))
        valid_states = [s for s in states if not s.get("terminal")]
        terminal_states = [s for s in states if s.get("terminal")]

        # Handle terminal articles: insert + mark PG_DONE with fallback values.
        # Each state is accounted individually so a partial failure counts
        # only the actually-failed articles; per-state errors are logged and
        # reflected in the returned counts (Rule 12 — no silent swallowing).
        if terminal_states:
            completed, failed = await self._handle_terminal_states(terminal_states)
            batch_completed += completed
            batch_failed += failed

        if not valid_states:
            return batch_completed, batch_failed

        # PG persistence — on failure, skip graph persistence
        if self._article_repo:
            try:
                await self._persist_articles_to_pg(valid_states)
            except Exception as exc:
                return await self._handle_pg_persist_failure(
                    valid_states, exc, batch_total, batch_completed, batch_failed
                )

        # Graph persistence
        if self._graph_writer:
            return await self._persist_to_graph_batch(
                valid_states, batch_total, batch_completed, batch_failed
            )

        # graph_writer is None — graph persistence silently skipped.
        # Articles remain in PG_DONE status (set by bulk_upsert) for
        # retry_neo4j_writes to pick up when graph store becomes available.
        # Do NOT increment batch_completed: graph write did not happen.
        for state in valid_states:
            log.error(
                "graph_writer_unavailable_skip_graph_persist",
                article_id=state.get("article_id"),
                url=state["raw"].url[:100] if state.get("raw") else "unknown",
            )
        return batch_completed, batch_failed

    async def _handle_terminal_states(self, states: list[PipelineState]) -> tuple[int, int]:
        """Insert and mark terminal articles as PG_DONE.

        Terminal articles (is_news=False) are inserted into the database with
        fallback values so API queries can return them. If the
        article already exists (PENDING), it is updated to PG_DONE.

        Args:
            states: Terminal pipeline states to persist.

        Returns:
            Tuple of (succeeded_count, failed_count). A failing state does
            not abort the remaining states; every failure is logged with its
            URL (Rule 12) and reflected in the counts.
        """
        succeeded = 0
        failed_count = 0
        if not states or not self._article_repo:
            return succeeded, failed_count
        for state in states:
            source_url = state["raw"].url if state.get("raw") else "unknown"
            try:
                # First, try to mark existing PENDING article as PG_DONE
                updated = await self._article_repo.mark_terminal_by_url(source_url)
                if updated:
                    log.info("terminal_article_status_updated", url=source_url[:50])
                    succeeded += 1
                    continue
                # Article doesn't exist — insert it via bulk_upsert.
                # NOTE: bulk_upsert/_upsert_chunk filters out terminal states,
                # so we must strip the terminal flag before passing it in.
                # We also set fallback values for terminal articles
                # because mark_terminal_by_url only updates PENDING articles
                # (bulk_upsert sets PG_DONE, so mark_terminal_by_url won't match).
                insert_state = dict(state)
                insert_state.pop("terminal", None)
                # fallback values for terminal (non-news) articles
                insert_state.setdefault("category", "其他")
                insert_state.setdefault("language", "unknown")
                insert_state.setdefault("region", "unknown")
                insert_state.setdefault("score", 0.0)
                # Log-only marker distinguishing "not analyzed" from genuine
                # low score (bulk_upsert mappers ignore this key; not persisted).
                insert_state.setdefault("is_analyzed", False)
                if "sentiment" not in insert_state:
                    insert_state["sentiment"] = {"sentiment_score": 0.0}
                if "credibility" not in insert_state:
                    insert_state["credibility"] = {"score": 0.0}
                article_ids = await self._article_repo.bulk_upsert([insert_state])
                inserted_id = article_ids[0] if article_ids else None
                if inserted_id is not None:
                    succeeded += 1
                    log.info(
                        "terminal_article_inserted",
                        url=source_url[:50],
                        article_id=str(inserted_id),
                        is_analyzed=insert_state.get("is_analyzed", False),
                    )
                else:
                    failed_count += 1
                    log.error(
                        "terminal_article_insert_failed",
                        url=source_url[:50],
                        reason="upsert failed after retries",
                    )
            except Exception as exc:
                failed_count += 1
                log.error(
                    "terminal_article_persist_failed",
                    url=source_url[:50],
                    error=str(exc),
                )
        return succeeded, failed_count

    async def _persist_articles_to_pg(self, valid_states: list[PipelineState]) -> None:
        """Persist articles to PostgreSQL via bulk_upsert.

        Raises:
            Exception: If bulk_upsert or vector persistence fails. The caller
                is responsible for calling _handle_pg_persist_failure.
        """
        article_ids = await self._article_repo.bulk_upsert(valid_states)
        failed_states = [state for state, aid in zip(valid_states, article_ids) if aid is None]
        if failed_states:
            log.error(
                "persist_articles_partial_failure",
                failed_count=len(failed_states),
                failed_urls=[getattr(s.get("raw"), "url", "unknown") for s in failed_states],
            )
        log.info(
            "persist_articles_committed",
            article_ids=[str(aid) for aid in article_ids if aid is not None],
            count=len(article_ids) - len(failed_states),
        )
        for state, aid in zip(valid_states, article_ids):
            if aid is None:
                # Failed upsert: leave article_id unset so downstream
                # (vectors, graph, status) skips this state instead of
                # writing another article's id.
                continue
            state["article_id"] = str(aid)
            # persist_status is set to STORED in bulk_upsert._upsert_chunk

        await self._persist_vectors(valid_states)
        log.info("batch_pg_persisted", count=len(article_ids) - len(failed_states))

    async def _persist_vectors(self, valid_states: list[PipelineState]) -> None:
        """Persist article vectors to the vector repository."""
        if not self._vector_repo:
            return
        vector_data = []
        for state in valid_states:
            if "vectors" in state:
                vectors = state["vectors"]
                article_id = state.get("article_id")
                log.debug(
                    "persist_vectors_check",
                    article_id=article_id,
                    has_title=("title" in vectors if isinstance(vectors, dict) else False),
                    has_content=("content" in vectors if isinstance(vectors, dict) else False),
                )
                if (
                    article_id is None
                    or not isinstance(vectors, dict)
                    or "title" not in vectors
                    or "content" not in vectors
                ):
                    continue
                vector_data.append(
                    (
                        uuid.UUID(article_id),
                        vectors.get("title"),
                        vectors.get("content"),
                        vectors.get("model_id", "unknown"),
                    )
                )
            else:
                log.debug("persist_vectors_missing", article_id=state.get("article_id"))
        if vector_data:
            log.info(
                "persist_vectors_about_to_insert",
                article_ids=[str(v[0]) for v in vector_data],
                count=len(vector_data),
            )
            count = await self._vector_repo.bulk_upsert_article_vectors(vector_data)
            log.debug("vectors_bulk_persisted", count=count)

    async def _handle_pg_persist_failure(
        self,
        valid_states: list[PipelineState],
        exc: Exception,
        batch_total: int,
        batch_completed: int,
        batch_failed: int,
    ) -> tuple[int, int]:
        """Handle PG persistence failure.

        Marks all valid articles as failed, updates counters, and returns
        so the caller skips graph persistence.
        """
        log.error(
            "persist_batch_pg_failed",
            error=str(exc),
            exc_type=type(exc).__name__,
            traceback=traceback.format_exc(),
        )
        # All articles in batch failed due to PG error
        for state in valid_states:
            batch_failed += 1
            self._log_progress(
                state["raw"].url if state.get("raw") else "unknown",
                batch_total,
                batch_completed,
                batch_failed,
            )
        # Log article IDs for debugging
        for state in valid_states:
            if state.get("article_id"):
                log.warning("persist_debug_article_exists", article_id=state["article_id"])
        # Mark articles as failed
        for state in valid_states:
            if state.get("article_id"):
                try:
                    await self._article_repo.mark_failed(
                        uuid.UUID(state["article_id"]), f"PG error: {exc!s}"
                    )
                except Exception as mark_exc:
                    log.error(
                        "mark_failed_after_pg_error_failed",
                        article_id=state.get("article_id"),
                        original_error=str(exc),
                        mark_error=str(mark_exc),
                    )
        return batch_completed, batch_failed

    async def _persist_to_graph_batch(
        self,
        valid_states: list[PipelineState],
        batch_total: int,
        batch_completed: int,
        batch_failed: int,
    ) -> tuple[int, int]:
        """Persist articles to Neo4j using batch write with per-article fallback."""
        log.debug(
            "persist_batch_graph_writer_check",
            has_graph_writer=self._graph_writer is not None,
        )
        if hasattr(self._graph_writer, "write_batch"):
            try:
                result = await self._graph_writer.write_batch(
                    valid_states, concurrency=self._phase3_concurrency
                )
                log.info(
                    "neo4j_batch_write_complete",
                    total=len(valid_states),
                    success=len(result.get("article_ids", [])),
                    failed=len(result.get("errors", [])),
                )
                # Update article IDs and persist status — success set only.
                # 旧实现先对全部 valid_states 置 done_status 再对失败项
                # mark_failed：mark_failed 抛错会留下「图库无数据但状态
                # NEO4J_DONE」的脏状态且永不重试（fail-open）。
                succeeded_ids = set(result.get("article_ids", []))
                error_ids = {aid for aid, _ in result.get("errors", [])}
                for i, state in enumerate(valid_states):
                    if i < len(result.get("neo4j_ids", [])):
                        state["neo4j_ids"] = result["neo4j_ids"][i]
                    article_id = state.get("article_id")
                    if (
                        article_id
                        and article_id in succeeded_ids
                        and article_id not in error_ids
                        and self._article_repo
                    ):
                        try:
                            await self._article_repo.update_persist_status(
                                uuid.UUID(article_id), self._graph_writer.done_status
                            )
                        except Exception as status_exc:
                            # 置位失败保持 PG_DONE → retry_neo4j_writes 可重试，
                            # 严禁吞掉后假装成功（Rule 12）。
                            log.error(
                                "update_persist_status_failed",
                                article_id=article_id,
                                error=str(status_exc),
                                exc_type=type(status_exc).__name__,
                            )
                # Log errors and mark failed articles
                for article_id_str, error_msg in result.get("errors", []):
                    log.error(
                        "persist_neo4j_batch_failed",
                        article_id=article_id_str,
                        error=error_msg,
                    )
                    batch_failed += 1
                    # Mark article as failed so it doesn't stay stuck
                    # in PG_DONE. Previously only logged, leaving articles in
                    # a "waiting for graph" state that never resolves.
                    if article_id_str and article_id_str != "unknown" and self._article_repo:
                        try:
                            await self._article_repo.mark_failed(
                                uuid.UUID(article_id_str),
                                f"Graph batch write failed: {error_msg}",
                            )
                        except (ValueError, TypeError) as parse_exc:
                            log.warning(
                                "mark_failed_invalid_article_id",
                                article_id_str=article_id_str,
                                error=str(parse_exc),
                            )
                        except Exception as mark_exc:
                            log.error(
                                "mark_failed_after_batch_error_failed",
                                article_id=article_id_str,
                                original_error=error_msg,
                                mark_error=str(mark_exc),
                            )
                # Success count
                persisted_ids_raw = result.get("article_ids", [])
                batch_completed += len(persisted_ids_raw)
                # set: the membership test below runs once per state — a list
                # would make this section O(len(valid_states) ** 2).
                persisted_ids = set(persisted_ids_raw)
                # Log progress for each successful article
                for state in valid_states:
                    if state.get("article_id") in persisted_ids:
                        self._log_progress(
                            state["raw"].url if state.get("raw") else "unknown",
                            batch_total,
                            batch_completed,
                            batch_failed,
                        )
                return batch_completed, batch_failed
            except Exception as exc:
                log.error(
                    "neo4j_batch_write_failed",
                    error=str(exc),
                    exc_type=type(exc).__name__,
                )
                # Fallback to per-article write
                log.warning("falling_back_to_per_article_write")

        # Per-article write (fallback after batch failure, or no batch support)
        for state in valid_states:
            batch_completed, batch_failed = await self._persist_to_graph_single(
                state, batch_total, batch_completed, batch_failed
            )
        return batch_completed, batch_failed

    async def _persist_to_graph_single(
        self,
        state: PipelineState,
        batch_total: int,
        batch_completed: int,
        batch_failed: int,
    ) -> tuple[int, int]:
        """Persist a single article to Neo4j.

        Used by both the batch-write fallback path and the no-batch-support path
        to deduplicate per-article write logic.
        """
        try:
            neo4j_ids = await self._graph_writer.write(state)
            state["neo4j_ids"] = neo4j_ids
            if self._article_repo and state.get("article_id"):
                await self._article_repo.update_persist_status(
                    uuid.UUID(state["article_id"]), self._graph_writer.done_status
                )
            batch_completed += 1
            self._log_progress(
                state["raw"].url if state.get("raw") else "unknown",
                batch_total,
                batch_completed,
                batch_failed,
            )
            return batch_completed, batch_failed
        except Exception as exc:
            return await self._handle_graph_persist_failure(
                state, exc, batch_total, batch_completed, batch_failed
            )

    async def _handle_graph_persist_failure(
        self,
        state: PipelineState,
        exc: Exception,
        batch_total: int,
        batch_completed: int,
        batch_failed: int,
    ) -> tuple[int, int]:
        """Handle Neo4j persistence failure for a single article."""
        log.error(
            "persist_neo4j_failed",
            article_id=state.get("article_id"),
            error=str(exc),
        )
        if state.get("article_id") and self._article_repo:
            try:
                await self._article_repo.mark_failed(
                    uuid.UUID(state["article_id"]), f"Neo4j error: {exc!s}"
                )
            except Exception as mark_exc:
                log.error(
                    "mark_failed_after_neo4j_persist_error_failed",
                    article_id=state.get("article_id"),
                    original_error=str(exc),
                    mark_error=str(mark_exc),
                )

        # Circuit-open means the graph DB is intentionally bypassed —
        # queue the full state in pending_sync so the retry job can restore
        # entities/relations later (payload keys match reconstruct_state_from_payload).
        if isinstance(exc, Neo4jWriteCircuitOpen) and self._pending_sync_repo is not None:
            try:
                state_payload = {
                    key: value
                    for key, value in state.items()
                    if key != "raw" and not key.startswith("_")
                }
                raw = state.get("raw")
                if raw is not None:
                    state_payload["raw"] = {
                        "url": getattr(raw, "url", ""),
                        "title": getattr(raw, "title", ""),
                        "source": getattr(raw, "source", ""),
                        "source_host": getattr(raw, "source_host", ""),
                        "source_id": getattr(raw, "source_id", ""),
                        "body": getattr(raw, "body", ""),
                        "publish_time": str(getattr(raw, "publish_time", "") or ""),
                    }
                state_payload["circuit_open_reason"] = "neo4j_write_circuit_open"
                await self._pending_sync_repo.upsert(
                    uuid.UUID(state["article_id"]),
                    "neo4j_write",
                    state_payload,
                )
                log.warning(
                    "neo4j_write_circuit_open_queued_pending_sync",
                    article_id=state.get("article_id"),
                )
            except Exception as sync_exc:
                log.error(
                    "pending_sync_upsert_after_circuit_open_failed",
                    article_id=state.get("article_id"),
                    error=str(sync_exc),
                )

        batch_failed += 1
        self._log_progress(
            state["raw"].url if state.get("raw") else "unknown",
            batch_total,
            batch_completed,
            batch_failed,
        )
        return batch_completed, batch_failed

    def _log_progress(self, url: str, total: int, completed: int, failed: int) -> None:
        """Log batch progress after each article completes.

        Args:
            url: URL of the processed article.
            total: Total articles in batch.
            completed: Number of completed articles.
            failed: Number of failed articles.
        """
        rate = (completed / total * 100) if total > 0 else 0.0
        log.info(f"[{completed}/{total}] {rate:.1f}% success ({failed} failed) | {url}")
