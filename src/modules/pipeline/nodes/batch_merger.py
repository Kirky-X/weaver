# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Batch Merger pipeline node — Union-Find based article merging."""

from __future__ import annotations

import asyncio
import time
import traceback
import uuid
from typing import TYPE_CHECKING, Any

import numpy as np

from core.db.models import PersistStatus
from core.llm.client import LLMClient
from core.llm.output_validator import MergerOutput
from core.llm.types import CallPoint
from core.observability.logging import get_logger
from core.observability.metrics import metrics
from core.prompt.loader import PromptLoader
from modules.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.protocols import ArticleRepository, VectorRepository
    from modules.knowledge.graph.writer import Neo4jWriter

log = get_logger("node.batch_merger")


class UnionFind:
    """Path-compressed Union-Find with rank optimization.

    O(α(n)) amortized complexity per operation.
    """

    def __init__(self, elements: list[str]) -> None:
        self._parent = {e: e for e in elements}
        self._rank = dict.fromkeys(elements, 0)

    def find(self, x: str) -> str:
        """Find root with path compression."""
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, x: str, y: str) -> None:
        """Union by rank."""
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1

    def add(self, element: str) -> None:
        """Dynamically add an element."""
        if element not in self._parent:
            self._parent[element] = element
            self._rank[element] = 0

    def get_groups(self) -> dict[str, list[str]]:
        """Get all groups as root → members mapping."""
        groups: dict[str, list[str]] = {}
        for e in self._parent:
            root = self.find(e)
            groups.setdefault(root, []).append(e)
        return groups


class BatchMergerNode:
    """Batch-level Merger using Union-Find + pgvector + LLM.

    Algorithm:
    1. Use pgvector batch similarity query instead of O(n²) matrix.
    2. Cross-query pgvector for historical similar articles.
    3. Two-pass Union-Find to ensure each article belongs to one group.
    4. LLM merge for each group with > 1 member.

    Args:
        llm: LLM client for merge calls.
        prompt_loader: Prompt loader for version tracking.
        vector_repo: Vector repository for pgvector queries.
        article_repo: Article repository for PostgreSQL operations.
        neo4j_writer: Neo4j writer for graph operations.
    """

    SIMILARITY_THRESHOLD = 0.80
    BATCH_SIMILARITY_LIMIT = 50

    def __init__(
        self,
        llm: LLMClient,
        prompt_loader: PromptLoader,
        vector_repo: VectorRepository | None = None,
        article_repo: ArticleRepository | None = None,
        neo4j_writer: Neo4jWriter | None = None,
    ) -> None:
        self._llm = llm
        self._prompt_loader = prompt_loader
        self._vector_repo = vector_repo
        self._article_repo = article_repo
        self._neo4j_writer = neo4j_writer

    async def execute_batch(self, states: list[PipelineState]) -> list[PipelineState]:
        """Execute batch merging on a list of pipeline states.

        Args:
            states: List of PipelineState dicts after vectorization.

        Returns:
            Modified states with merge information.
        """
        start_time = time.perf_counter()
        active_states = [s for s in states if not s.get("terminal")]
        if not active_states:
            return states

        ids = [s["raw"].url for s in active_states]
        vectors = [s["vectors"]["content"] for s in active_states]
        uf = UnionFind(ids)

        if self._vector_repo and hasattr(self._vector_repo, "batch_find_similar"):
            await self._batch_similarity_query(active_states, vectors, uf)
        else:
            await self._intra_batch_similarity(active_states, vectors, uf)

        if self._vector_repo:
            cross_tasks = [self._cross_query(s, uf, ids) for s in active_states]
            await asyncio.gather(*cross_tasks)

        groups = uf.get_groups()
        merge_tasks = []
        merged_count = 0
        for root, members in groups.items():
            if len(members) <= 1:
                continue
            group_states = [s for s in active_states if s["raw"].url in members]
            merge_tasks.append(self._llm_merge(group_states))
            merged_count += len(members) - 1  # Count merged articles

        if merge_tasks:
            await asyncio.gather(*merge_tasks)

        # Record metrics
        elapsed = time.perf_counter() - start_time
        metrics.dedup_total.labels(stage="vector").inc(merged_count)
        metrics.dedup_processing_time.labels(stage="vector").observe(elapsed)

        # Update ratio gauge
        if len(active_states) > 0:
            ratio = merged_count / len(active_states)
            metrics.dedup_ratio.labels(stage="vector").set(ratio)

        log.info(
            "batch_merge_complete",
            total=len(active_states),
            groups=len([g for g in groups.values() if len(g) > 1]),
            merged=merged_count,
        )
        return states

    async def _batch_similarity_query(
        self,
        states: list[PipelineState],
        vectors: list[list[float]],
        uf: UnionFind,
    ) -> None:
        """Use pgvector batch similarity query for O(n log n) complexity."""
        try:
            queries = [(uuid.uuid4(), vec) for vec in vectors]
            batch_results = await self._vector_repo.batch_find_similar(
                queries=queries,
                threshold=self.SIMILARITY_THRESHOLD,
                limit=self.BATCH_SIMILARITY_LIMIT,
            )

            url_to_index = {s["raw"].url: i for i, s in enumerate(states)}
            for i, (query_id, _) in enumerate(queries):
                hits = batch_results.get(query_id, [])
                for hit in hits:
                    if hit.similarity > self.SIMILARITY_THRESHOLD:
                        j = url_to_index.get(hit.article_id)
                        if j is not None and i != j:
                            if states[i].get("category") == states[j].get("category"):
                                uf.union(states[i]["raw"].url, states[j]["raw"].url)
        except Exception as exc:
            log.warning("batch_similarity_query_failed", error=str(exc))
            await self._intra_batch_similarity(states, vectors, uf)

    async def _intra_batch_similarity(
        self,
        states: list[PipelineState],
        vectors: list[list[float]],
        uf: UnionFind,
    ) -> None:
        """Fallback to O(n²) intra-batch similarity matrix."""
        mat = np.array(vectors, dtype=np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        normed = mat / (norms + 1e-8)
        sim_matrix = normed @ normed.T

        n = len(states)
        for i in range(n):
            for j in range(i + 1, n):
                if sim_matrix[i, j] > self.SIMILARITY_THRESHOLD:
                    if states[i].get("category") == states[j].get("category"):
                        uf.union(states[i]["raw"].url, states[j]["raw"].url)

    async def _cross_query(self, state: PipelineState, uf: UnionFind, ids: list[str]) -> None:
        """Query historical similar articles and extend Union-Find."""
        if not self._vector_repo:
            return

        try:
            hits = await self._vector_repo.find_similar(
                embedding=state["vectors"]["content"],
                category=state.get("category"),
                threshold=self.SIMILARITY_THRESHOLD,
                limit=20,
            )
            for hit in hits:
                uf.add(hit.article_id)
                if state.get("category") == hit.category:
                    uf.union(state["raw"].url, hit.article_id)
        except Exception as exc:
            log.warning(
                "cross_query_failed",
                url=state["raw"].url,
                category=state.get("category"),
                error_type=type(exc).__name__,
                error=str(exc),
            )

    async def _llm_merge(self, group_states: list[PipelineState]) -> None:
        """Merge a group of similar articles via LLM."""
        articles_payload = [
            {
                "title": s["cleaned"]["title"],
                "body": s["cleaned"]["body"][:1000],
                "publish_time": str(s["raw"].publish_time) if s["raw"].publish_time else None,
                "source": s["raw"].source,
            }
            for s in group_states
        ]

        result: MergerOutput = await self._llm.call_at(
            CallPoint.MERGER,
            {
                "articles": articles_payload,
                "article_id": group_states[0].get("article_id"),
                "task_id": group_states[0].get("task_id"),
            },
            output_model=MergerOutput,
        )

        primary = max(
            group_states,
            key=lambda s: s["raw"].publish_time or 0,
        )
        primary["cleaned"]["body"] = result.merged_body
        primary["cleaned"]["title"] = result.merged_title
        primary["merged_source_ids"] = [s["raw"].url for s in group_states if s is not primary]

        for s in group_states:
            if s is not primary:
                s["is_merged"] = True
                s["merged_into"] = primary["raw"].url

        primary.setdefault("prompt_versions", {})["merger"] = self._prompt_loader.get_version(
            "merger"
        )

    async def persist_batch_saga(
        self,
        states: list[PipelineState],
    ) -> dict[str, Any]:
        """Persist batch with Saga pattern for atomic cross-database consistency.

        Implements two-phase commit with compensation:
        1. Phase 1: Persist to PostgreSQL, record successful IDs
        2. Phase 2: Persist to Neo4j
        3. Compensation: If Phase 2 fails, delete PostgreSQL records

        Args:
            states: List of pipeline states to persist.

        Returns:
            Dict containing:
            - success: Whether the entire saga completed
            - pg_ids: List of PostgreSQL article IDs
            - neo4j_ids: List of Neo4j node IDs
            - compensation_executed: Whether compensation was triggered
            - error: Error message if failed
        """
        result = {
            "success": False,
            "pg_ids": [],
            "neo4j_ids": [],
            "compensation_executed": False,
            "error": None,
        }

        valid_states = [s for s in states if not s.get("terminal")]
        if not valid_states:
            result["success"] = True
            return result

        # Idempotency: Check for duplicate articles by URL
        urls_to_check = [s["raw"].url for s in valid_states]
        existing_urls = await self._article_repo.get_existing_urls(urls_to_check)

        # Filter out duplicates, keep only new articles
        new_states = [s for s in valid_states if s["raw"].url not in existing_urls]
        skipped_count = len(valid_states) - len(new_states)

        if skipped_count > 0:
            log.info(
                "saga_duplicates_skipped",
                total=len(valid_states),
                skipped=skipped_count,
                new_articles=len(new_states),
            )

        if not new_states:
            log.info("saga_all_duplicates")
            result["success"] = True
            return result

        # Track article IDs that have vectors written (for compensation cleanup)
        vector_article_ids: list[uuid.UUID] = []

        # Phase 1: Persist to PostgreSQL
        try:
            if not self._article_repo:
                raise RuntimeError("Article repository not configured")

            article_ids = await self._article_repo.bulk_upsert(new_states)
            result["pg_ids"] = [str(aid) for aid in article_ids]

            # Update persist status and link IDs to states
            for state, aid in zip(new_states, article_ids):
                state["article_id"] = str(aid)
                await self._article_repo.update_persist_status(aid, PersistStatus.PG_DONE)

            # Persist vectors
            if self._vector_repo:
                vector_data = []
                for state in new_states:
                    if "vectors" in state:
                        vectors = state["vectors"]
                        if (
                            isinstance(vectors, dict)
                            and "title" in vectors
                            and "content" in vectors
                        ):
                            art_id = uuid.UUID(state["article_id"])
                            vector_data.append(
                                (
                                    art_id,
                                    vectors.get("title"),
                                    vectors.get("content"),
                                    vectors.get("model_id", "unknown"),
                                )
                            )
                            vector_article_ids.append(art_id)
                if vector_data:
                    await self._vector_repo.bulk_upsert_article_vectors(vector_data)

            log.info(
                "saga_phase1_complete",
                pg_count=len(article_ids),
            )

        except Exception as exc:
            error_msg = f"Phase 1 (PostgreSQL) failed: {type(exc).__name__}: {exc}"
            result["error"] = error_msg
            log.error(
                "saga_phase1_failed",
                error=error_msg,
                traceback=traceback.format_exc(),
            )
            # Mark failed for all attempted states
            for state in valid_states:
                if state.get("article_id"):
                    try:
                        await self._article_repo.mark_failed(
                            uuid.UUID(state["article_id"]),
                            error_msg,
                        )
                    except Exception:
                        pass
            # Clean up article vectors written before this exception
            if vector_article_ids and self._vector_repo:
                try:
                    deleted = await self._vector_repo.delete_article_vectors_by_article_ids(
                        vector_article_ids
                    )
                    log.info("saga_phase1_vectors_cleaned", count=deleted)
                except Exception as vec_exc:
                    log.warning(
                        "saga_phase1_vector_cleanup_failed",
                        error=str(vec_exc),
                        article_ids=[str(a) for a in vector_article_ids],
                    )
            return result

        # Phase 2: Persist to Neo4j
        neo4j_errors = []
        successful_neo4j_ids = []

        for state in new_states:
            if not self._neo4j_writer:
                continue

            try:
                neo4j_ids = await self._neo4j_writer.write(state)
                state["neo4j_ids"] = neo4j_ids
                successful_neo4j_ids.extend(neo4j_ids)

                if self._article_repo and state.get("article_id"):
                    await self._article_repo.update_persist_status(
                        uuid.UUID(state["article_id"]),
                        PersistStatus.NEO4J_DONE,
                    )
            except Exception as exc:
                error_msg = f"Neo4j write failed: {type(exc).__name__}: {exc}"
                neo4j_errors.append((state.get("article_id"), error_msg))
                log.error(
                    "saga_phase2_article_failed",
                    article_id=state.get("article_id"),
                    error=error_msg,
                )

        result["neo4j_ids"] = successful_neo4j_ids

        # Check if Phase 2 had failures
        if neo4j_errors:
            log.warning(
                "saga_phase2_partial_failure",
                failed_count=len(neo4j_errors),
                total=len(new_states),
            )

            # Trigger compensation transaction
            result["compensation_executed"] = True
            compensation_errors = []

            for pg_id_str, error_msg in neo4j_errors:
                try:
                    pg_id = uuid.UUID(pg_id_str)
                    # Delete from PostgreSQL
                    await self._article_repo.delete(pg_id)
                    log.info(
                        "saga_compensation_deleted",
                        article_id=str(pg_id),
                    )
                except Exception as comp_exc:
                    comp_error = f"Compensation failed for {pg_id_str}: {comp_exc}"
                    compensation_errors.append(comp_error)
                    log.error(
                        "saga_compensation_failed",
                        article_id=str(pg_id),
                        error=comp_error,
                    )

            if compensation_errors:
                log.error(
                    "saga_compensation_incomplete",
                    errors=compensation_errors,
                    message="sync_neo4j_with_postgres background task will reconcile",
                )
                # Alert would be raised here in production
                # For now, rely on the sync_neo4j_with_postgres scheduled job

            result["error"] = f"Phase 2 failed for {len(neo4j_errors)} articles"
            result["success"] = False
            return result

        # All phases succeeded
        result["success"] = True
        log.info(
            "saga_complete",
            pg_count=len(result["pg_ids"]),
            neo4j_count=len(result["neo4j_ids"]),
        )
        return result
