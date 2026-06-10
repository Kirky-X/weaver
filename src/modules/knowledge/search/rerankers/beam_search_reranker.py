# Copyright (c) 2026 KirkyX. All Rights Reserved
"""BeamSearchReranker — standalone reusable beam search reranking.

Extracted from AdaptiveSearchEngine's _beam_search method into a
reusable component for the knowledge search pipeline.

Cumulative score formula:
    cum_score = cum_score * 0.7 + neighbor_score * 0.3

Pruning: at each depth step, keep only top beam_width candidates.
"""

from __future__ import annotations

from typing import Any

from core.observability.logging import get_logger

log = get_logger(__name__)


class BeamSearchReranker:
    """Standalone beam search reranker for graph-based result refinement.

    Implements: SearchReranker

    Expands candidate entities through graph neighbors, accumulating
    scores and pruning to beam_width at each depth step.

    Args:
        beam_width: Number of candidates to keep at each step (default 5).
        decay_factor: Weight for cumulative score (default 0.7).
        expansion_weight: Weight for new neighbor score (default 0.3).
    """

    def __init__(
        self,
        beam_width: int = 5,
        decay_factor: float = 0.7,
        expansion_weight: float = 0.3,
    ) -> None:
        self._beam_width = beam_width
        self._decay_factor = decay_factor
        self._expansion_weight = expansion_weight

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        graph: Any = None,
        depth: int = 2,
    ) -> list[dict[str, Any]]:
        """Rerank candidates using beam search expansion.

        Args:
            query: The search query (used for logging).
            candidates: List of candidate dicts with fusion_score.
            graph: Optional graph object with get_neighbors(entity_id) method.
            depth: Number of expansion hops (default 2).

        Returns:
            Reranked candidates limited to beam_width, sorted by cumulative_score.
        """
        if not candidates:
            return []

        # Initialize frontier with cumulative_score = fusion_score
        frontier: list[dict[str, Any]] = []
        for c in candidates:
            entry = {**c, "cumulative_score": c.get("fusion_score", c.get("score", 0.0))}
            frontier.append(entry)

        visited: set[str] = set()
        all_results: list[dict[str, Any]] = []

        for d in range(depth + 1):
            if not frontier:
                break

            # Collect results from current frontier
            for node in frontier:
                node_id = node.get("id", "")
                if node_id and node_id not in visited:
                    visited.add(node_id)
                    all_results.append(node)

            # No graph or last depth — no expansion
            if graph is None or d >= depth:
                break

            # Expand: get neighbors for each frontier node
            next_candidates: list[dict[str, Any]] = []
            for node in frontier:
                node_id = node.get("id", "")
                if not node_id:
                    continue

                try:
                    neighbors = graph.get_neighbors(node_id)
                except Exception as exc:
                    log.warning("beam_expand_failed", node_id=node_id, error=str(exc))
                    continue

                if not neighbors:
                    continue

                for n in neighbors:
                    n_id = n.get("id", "")
                    if n_id in visited:
                        continue

                    neighbor_score = n.get("fusion_score", n.get("score", 0.0))
                    cumulative = (
                        node["cumulative_score"] * self._decay_factor
                        + neighbor_score * self._expansion_weight
                    )
                    next_candidates.append({**n, "cumulative_score": cumulative})

            # Prune: keep top beam_width
            next_candidates.sort(key=lambda x: x["cumulative_score"], reverse=True)
            frontier = next_candidates[: self._beam_width]

        # Sort all results by cumulative_score and limit to beam_width
        all_results.sort(key=lambda x: x["cumulative_score"], reverse=True)
        return all_results[: self._beam_width]
