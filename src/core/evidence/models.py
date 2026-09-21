# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Pydantic models for evidence sampling LLM responses."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

# 单条关键事实长度上界：LLM 输出经 _synthesize_regions 拼入下游 prompt，
# 无界字符串会放大下游 token 消耗（审查 L-2）。
KeyFact = Annotated[str, StringConstraints(max_length=500)]


class EvidenceScoreOutput(BaseModel):
    """LLM response for evidence quality scoring.

    Used by MCSampler to evaluate the relevance and quality of
    sampled text regions from long documents.
    """

    region_id: str = Field(
        default="",
        max_length=8,
        description="Echoed region identifier (R1..Rn) for order-independent alignment",
    )
    relevance_score: float = Field(
        ge=0.0,
        le=1.0,
        description="How relevant is this sample to the main topic",
    )
    information_density: float = Field(
        ge=0.0,
        le=1.0,
        description="How much useful information is packed in this sample",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall confidence in this evaluation",
    )
    key_facts: list[KeyFact] = Field(
        default_factory=list,
        description="Key facts extracted from this sample",
    )


class EvidenceBatchScoreOutput(BaseModel):
    """LLM response for batched evidence region scoring.

    Single-call batch format: one JSON object whose ``scores`` array covers
    the numbered regions (R1..Rn); each element echoes its ``region_id`` so
    the sampler can align scores without trusting array order.
    """

    scores: list[EvidenceScoreOutput] = Field(
        description="Per-region scores; each element echoes region_id (R1..Rn)",
    )
