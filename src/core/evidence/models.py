# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pydantic models for evidence sampling LLM responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EvidenceScoreOutput(BaseModel):
    """LLM response for evidence quality scoring.

    Used by MCSampler to evaluate the relevance and quality of
    sampled text regions from long documents.
    """

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
    key_facts: list[str] = Field(
        default_factory=list,
        description="Key facts extracted from this sample",
    )


class ROISummaryOutput(BaseModel):
    """LLM response for Region of Interest (ROI) summary synthesis.

    Used by MCSampler to combine multiple sampled regions into
    a coherent summary of the document.
    """

    summary: str = Field(
        description="Synthesized summary from sampled regions",
    )
    main_topics: list[str] = Field(
        default_factory=list,
        description="Main topics identified in the document",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        default=0.5,
        description="Confidence in the summary quality",
    )
