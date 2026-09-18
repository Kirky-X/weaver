# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Shared vector math helpers."""

from __future__ import annotations

import math


def cosine_similarity(a: list[float] | None, b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First vector (can be None).
        b: Second vector.

    Returns:
        Cosine similarity in range [-1, 1], or 0 if a is None, either vector
        is empty, lengths differ, or either vector has zero norm.
        Negative values occur when vectors point in opposite directions.
    """
    if a is None or not a or not b:
        return 0.0

    if len(a) != len(b):
        return 0.0

    dot_product = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)
