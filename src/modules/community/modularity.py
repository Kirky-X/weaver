# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Modularity calculation for graph community quality assessment.

Based on GraphRAG's modularity implementation for evaluating
the quality of community partitions.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from core.observability.logging import get_logger

log = get_logger("community.modularity")


@dataclass
class ModularityResult:
    """Result of modularity calculation."""

    score: float
    resolution: float
    community_count: int
    community_sizes: dict[int, int]
    interpretation: str


class ModularityCalculator:
    """Calculate modularity score for graph partitions.

    Modularity measures the quality of a graph partition into communities.
    Higher values (closer to 1) indicate better community structure.

    The modularity Q is defined as:
    Q = (1/2m) * Σ[Aij - γ*(ki*kj)/(2m)] * δ(ci, cj)

    where:
    - m is total edge weight
    - Aij is edge weight between i and j
    - ki, kj are weighted degrees
    - γ is resolution parameter
    - δ(ci, cj) is 1 if i and j in same community, 0 otherwise
    """

    def __init__(self, resolution: float = 1.0) -> None:
        """Initialize modularity calculator.

        Args:
            resolution: Resolution parameter (default: 1.0).
                Higher values favor smaller communities.
        """
        self._resolution = resolution

    def calculate(
        self,
        edges: list[tuple[str, str, float]],
        partitions: dict[str, int],
    ) -> ModularityResult:
        """Calculate modularity score for given partitions.

        Args:
            edges: List of (source, target, weight) tuples.
            partitions: Mapping of node ID to community ID.

        Returns:
            ModularityResult with score and interpretation.
        """
        if not edges or not partitions:
            return ModularityResult(
                score=0.0,
                resolution=self._resolution,
                community_count=0,
                community_sizes={},
                interpretation="empty_graph",
            )

        total_weight = sum(e[2] for e in edges)
        if total_weight == 0:
            return ModularityResult(
                score=0.0,
                resolution=self._resolution,
                community_count=len(set(partitions.values())),
                community_sizes=self._get_community_sizes(partitions),
                interpretation="no_edges",
            )

        degree_sums: dict[str, float] = defaultdict(float)
        for source, target, weight in edges:
            degree_sums[source] += weight
            degree_sums[target] += weight

        community_internal: dict[int, float] = defaultdict(float)
        community_total: dict[int, float] = defaultdict(float)

        for source, target, weight in edges:
            src_comm = partitions.get(source, -1)
            tgt_comm = partitions.get(target, -1)

            if src_comm != -1:
                community_total[src_comm] += weight
            if tgt_comm != -1 and tgt_comm != src_comm:
                community_total[tgt_comm] += weight

            if src_comm == tgt_comm and src_comm != -1:
                community_internal[src_comm] += weight * 2

        modularity = 0.0
        for comm in set(partitions.values()):
            if comm == -1:
                continue
            intra = community_internal[comm]
            total = community_total[comm]
            modularity += intra - self._resolution * (total**2) / (2 * total_weight)

        modularity /= 2 * total_weight
        modularity = max(-1.0, min(1.0, modularity))

        community_sizes = self._get_community_sizes(partitions)
        interpretation = self._interpret_score(modularity)

        return ModularityResult(
            score=modularity,
            resolution=self._resolution,
            community_count=len(community_sizes),
            community_sizes=community_sizes,
            interpretation=interpretation,
        )

    def calculate_from_adjacency(
        self,
        adjacency: dict[str, dict[str, float]],
        partitions: dict[str, int],
    ) -> ModularityResult:
        """Calculate modularity from adjacency dict.

        Args:
            adjacency: Dict mapping node to dict of neighbors with weights.
            partitions: Mapping of node ID to community ID.

        Returns:
            ModularityResult with score and interpretation.
        """
        edges = []
        seen = set()

        for source, neighbors in adjacency.items():
            for target, weight in neighbors.items():
                edge_key = tuple(sorted([source, target]))
                if edge_key not in seen:
                    edges.append((source, target, weight))
                    seen.add(edge_key)

        return self.calculate(edges, partitions)

    def compare_partitions(
        self,
        edges: list[tuple[str, str, float]],
        partitions_list: list[dict[str, int]],
    ) -> list[ModularityResult]:
        """Compare multiple partition schemes.

        Args:
            edges: List of (source, target, weight) tuples.
            partitions_list: List of partition dicts to compare.

        Returns:
            List of ModularityResults sorted by score (descending).
        """
        results = [self.calculate(edges, partitions) for partitions in partitions_list]
        return sorted(results, key=lambda r: r.score, reverse=True)

    def find_optimal_resolution(
        self,
        edges: list[tuple[str, str, float]],
        partitions_func: callable,
        min_resolution: float = 0.1,
        max_resolution: float = 2.0,
        steps: int = 10,
    ) -> tuple[float, ModularityResult]:
        """Find optimal resolution parameter.

        Args:
            edges: List of (source, target, weight) tuples.
            partitions_func: Function that takes resolution and returns partitions.
            min_resolution: Minimum resolution to try.
            max_resolution: Maximum resolution to try.
            steps: Number of resolution values to try.

        Returns:
            Tuple of (optimal_resolution, best_result).
        """
        best_resolution = min_resolution
        best_result = None

        step_size = (max_resolution - min_resolution) / steps

        for i in range(steps + 1):
            resolution = min_resolution + i * step_size
            self._resolution = resolution

            partitions = partitions_func(resolution)
            result = self.calculate(edges, partitions)

            if best_result is None or result.score > best_result.score:
                best_result = result
                best_resolution = resolution

        return best_resolution, best_result

    @staticmethod
    def _get_community_sizes(partitions: dict[str, int]) -> dict[int, int]:
        """Get size of each community."""
        sizes: dict[int, int] = defaultdict(int)
        for comm in partitions.values():
            sizes[comm] += 1
        return dict(sizes)

    @staticmethod
    def _interpret_score(score: float) -> str:
        """Interpret modularity score."""
        if score >= 0.7:
            return "excellent"
        elif score >= 0.5:
            return "good"
        elif score >= 0.3:
            return "moderate"
        elif score >= 0.0:
            return "weak"
        else:
            return "poor"


def calculate_modularity(
    edges: list[tuple[str, str, float]],
    partitions: dict[str, int],
    resolution: float = 1.0,
) -> float:
    """Convenience function to calculate modularity score.

    Args:
        edges: List of (source, target, weight) tuples.
        partitions: Mapping of node ID to community ID.
        resolution: Resolution parameter.

    Returns:
        Modularity score.
    """
    calculator = ModularityCalculator(resolution=resolution)
    result = calculator.calculate(edges, partitions)
    return result.score
