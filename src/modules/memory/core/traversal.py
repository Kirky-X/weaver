# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Graph traversal algorithms for adaptive retrieval.

Implements MAGMA's Heuristic Beam Search with transition score calculation.
"""

from __future__ import annotations

import math

from core.utils.vector_math import cosine_similarity as cosine_similarity

from modules.memory.core.event_node import EventNode
from modules.memory.core.graph_types import INTENT_EDGE_WEIGHTS, EdgeType, IntentType


def calculate_transition_score(
    neighbor: EventNode,
    query_embedding: list[float],
    query_intent: IntentType,
    edge_type: EdgeType,
    *,
    lambda_structure: float = 1.0,
    lambda_semantic: float = 0.5,
) -> float:
    """Calculate transition score for graph traversal.

    Implements MAGMA Equation 5:
    S(n_j | n_i, q) = exp(λ₁·φ(type(e_ij), T_q) + λ₂·sim(v_j, q))

    Args:
        neighbor: The candidate node to transition to.
        query_embedding: Dense embedding of the query.
        query_intent: Classified intent of the query (WHY/WHEN/ENTITY/OPEN).
        edge_type: Type of the edge being traversed.
        lambda_structure: Weight for structural alignment (λ₁).
        lambda_semantic: Weight for semantic similarity (λ₂).

    Returns:
        Transition score (higher is better).
    """
    # Structural alignment: φ(type(e_ij), T_q)
    structural_score = INTENT_EDGE_WEIGHTS[query_intent].get(edge_type, 0.0)

    # Semantic similarity: sim(v_j, q)
    semantic_score = cosine_similarity(neighbor.embedding, query_embedding)

    # Combined score
    return math.exp(lambda_structure * structural_score + lambda_semantic * semantic_score)


# cosine_similarity is re-exported from the shared implementation in
# core.utils.vector_math (imported below).
