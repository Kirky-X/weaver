# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Enum types for community detection."""

from enum import StrEnum


class ModularityMetric(StrEnum):
    """Modularity calculation strategy.

    Defines three strategies for calculating graph modularity:

    - Graph: Calculate modularity over the entire graph (including disconnected components).
      May give artificially low scores for sparse graphs with many isolated islands.

    - LCC: Calculate modularity only for the Largest Connected Component.
      Ignores disconnected islands, focuses on the main connected structure.

    - WeightedComponents: Weighted average across all connected components.
      Weighs each component by its size, giving balanced score for graphs with multiple islands.
      Components smaller than min_component_size are excluded from weighted average.
    """

    Graph = "graph"
    LCC = "lcc"
    WeightedComponents = "weighted_components"
