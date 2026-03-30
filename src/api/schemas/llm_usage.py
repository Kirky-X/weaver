# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LLM usage statistics API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LLMUsageRecord(BaseModel):
    """Single LLM usage record with aggregated metrics."""

    time_bucket: datetime = Field(description="Time bucket for this record")
    label: str = Field(description="Label for grouping")
    call_point: str = Field(description="Call point identifier")
    llm_type: str = Field(description="LLM type: chat, embedding, rerank")
    provider: str = Field(description="Provider name")
    model: str = Field(description="Model name")
    call_count: int = Field(description="Total number of calls")
    input_tokens: int = Field(description="Total input tokens")
    output_tokens: int = Field(description="Total output tokens")
    total_tokens: int = Field(description="Total tokens")
    latency_avg_ms: float = Field(description="Average latency in milliseconds")
    latency_min_ms: float = Field(description="Minimum latency in milliseconds")
    latency_max_ms: float = Field(description="Maximum latency in milliseconds")
    success_count: int = Field(description="Number of successful calls")
    failure_count: int = Field(description="Number of failed calls")


class LLMUsageResponse(BaseModel):
    """Response for LLM usage query."""

    records: list[LLMUsageRecord] = Field(default_factory=list, description="Usage records")
    total: int = Field(default=0, description="Total number of records")


class LLMUsageSummary(BaseModel):
    """Summary statistics for LLM usage."""

    total_calls: int = Field(description="Total number of calls")
    total_input_tokens: int = Field(description="Total input tokens")
    total_output_tokens: int = Field(description="Total output tokens")
    total_tokens: int = Field(description="Total tokens")
    avg_latency_ms: float = Field(description="Average latency in milliseconds")
    max_latency_ms: float = Field(default=0.0, description="Maximum latency in milliseconds")
    min_latency_ms: float = Field(default=0.0, description="Minimum latency in milliseconds")
    success_rate: float = Field(description="Success rate (0.0 to 1.0)")
    error_types: dict[str, int] = Field(
        default_factory=dict,
        description="Error type breakdown",
    )


class LLMUsageByProvider(BaseModel):
    """LLM usage statistics grouped by provider."""

    provider: str = Field(description="Provider name")
    call_count: int = Field(description="Total number of calls")
    input_tokens: int = Field(default=0, description="Total input tokens")
    output_tokens: int = Field(default=0, description="Total output tokens")
    total_tokens: int = Field(description="Total tokens")
    avg_latency_ms: float = Field(default=0.0, description="Average latency in milliseconds")
    success_rate: float = Field(default=1.0, description="Success rate (0.0 to 1.0)")


class LLMUsageByModel(BaseModel):
    """LLM usage statistics grouped by model."""

    model: str = Field(description="Model name")
    provider: str = Field(description="Provider name")
    call_count: int = Field(description="Total number of calls")
    input_tokens: int = Field(default=0, description="Total input tokens")
    output_tokens: int = Field(default=0, description="Total output tokens")
    total_tokens: int = Field(description="Total tokens")
    avg_latency_ms: float = Field(default=0.0, description="Average latency in milliseconds")
    success_rate: float = Field(default=1.0, description="Success rate (0.0 to 1.0)")


class LLMUsageByCallPoint(BaseModel):
    """LLM usage statistics grouped by call point."""

    call_point: str = Field(description="Call point identifier")
    call_count: int = Field(description="Total number of calls")
    total_tokens: int = Field(description="Total tokens")
    avg_latency_ms: float = Field(default=0.0, description="Average latency in milliseconds")
    success_rate: float = Field(default=1.0, description="Success rate (0.0 to 1.0)")
