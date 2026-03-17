"""Batch Merger pipeline node — Union-Find based article merging."""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np

from core.llm.client import LLMClient
from core.llm.types import CallPoint
from core.llm.output_validator import MergerOutput
from core.prompt.loader import PromptLoader
from core.observability.logging import get_logger
from modules.pipeline.state import PipelineState

log = get_logger("node.batch_merger")


class UnionFind:
    """Path-compressed Union-Find with rank optimization.

    O(α(n)) amortized complexity per operation.
    """

    def __init__(self, elements: list[str]) -> None:
        self._parent = {e: e for e in elements}
        self._rank = {e: 0 for e in elements}

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
    """

    SIMILARITY_THRESHOLD = 0.80
    BATCH_SIMILARITY_LIMIT = 50

    def __init__(
        self,
        llm: LLMClient,
        prompt_loader: PromptLoader,
        vector_repo: Any = None,
    ) -> None:
        self._llm = llm
        self._prompt_loader = prompt_loader
        self._vector_repo = vector_repo

    async def execute_batch(
        self, states: list[PipelineState]
    ) -> list[PipelineState]:
        """Execute batch merging on a list of pipeline states.

        Args:
            states: List of PipelineState dicts after vectorization.

        Returns:
            Modified states with merge information.
        """
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
            cross_tasks = [
                self._cross_query(s, uf, ids) for s in active_states
            ]
            await asyncio.gather(*cross_tasks)

        groups = uf.get_groups()
        merge_tasks = []
        for root, members in groups.items():
            if len(members) <= 1:
                continue
            group_states = [s for s in active_states if s["raw"].url in members]
            merge_tasks.append(self._llm_merge(group_states))

        if merge_tasks:
            await asyncio.gather(*merge_tasks)

        log.info(
            "batch_merge_complete",
            total=len(active_states),
            groups=len([g for g in groups.values() if len(g) > 1]),
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
            batch_results = await self._vector_repo.batch_find_similar(
                embeddings=vectors,
                threshold=self.SIMILARITY_THRESHOLD,
                limit=self.BATCH_SIMILARITY_LIMIT,
            )

            for i, hits in enumerate(batch_results):
                for hit in hits:
                    if hit.get("article_id") and hit.get("similarity", 0) > self.SIMILARITY_THRESHOLD:
                        j = hit.get("batch_index")
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

    async def _cross_query(
        self, state: PipelineState, uf: UnionFind, ids: list[str]
    ) -> None:
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
            log.warning("cross_query_failed", url=state["raw"].url, error=str(exc))

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

        result: MergerOutput = await self._llm.call(
            CallPoint.MERGER,
            {"articles": articles_payload},
            output_model=MergerOutput,
        )

        primary = max(
            group_states,
            key=lambda s: s["raw"].publish_time or 0,
        )
        primary["cleaned"]["body"] = result.merged_body
        primary["cleaned"]["title"] = result.merged_title
        primary["merged_source_ids"] = [
            s["raw"].url for s in group_states if s is not primary
        ]

        for s in group_states:
            if s is not primary:
                s["is_merged"] = True
                s["merged_into"] = primary["raw"].url

        primary.setdefault("prompt_versions", {})["merger"] = (
            self._prompt_loader.get_version("merger")
        )
