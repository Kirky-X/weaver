# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Shared LLM usage query logic for admin and monitoring endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from api.schemas.response import APIResponse, success_response

if TYPE_CHECKING:
    from modules.analytics import LLMUsageRepo


async def query_llm_usage(
    repo: LLMUsageRepo,
    from_: datetime,
    to: datetime,
    group_by: str,
    granularity: str,
    provider: str | None = None,
    model: str | None = None,
    llm_type: str | None = None,
    call_point: str | None = None,
) -> APIResponse[dict]:
    """Core LLM usage query logic shared by admin and monitoring endpoints.

    Args:
        repo: LLM usage repository.
        from_: Start of time range.
        to: End of time range.
        group_by: Grouping dimension (summary/time/provider/model/call_point).
        granularity: Time granularity (hourly/daily/monthly).
        provider: Optional provider filter.
        model: Optional model filter.
        llm_type: Optional LLM type filter.
        call_point: Optional call point filter.

    Returns:
        APIResponse with grouped usage data.

    """
    if group_by == "summary":
        summary = await repo.get_summary(
            start_time=from_,
            end_time=to,
            provider=provider,
            model=model,
            llm_type=llm_type,
            call_point=call_point,
        )
        return success_response(
            {
                "group_by": "summary",
                "total_calls": summary["total_calls"],
                "total_input_tokens": summary["total_input_tokens"],
                "total_output_tokens": summary["total_output_tokens"],
                "total_tokens": summary["total_tokens"],
                "avg_latency_ms": summary["avg_latency_ms"],
                "max_latency_ms": summary.get("max_latency_ms", 0.0),
                "min_latency_ms": summary.get("min_latency_ms", 0.0),
                "success_rate": summary["success_rate"],
                "error_types": summary.get("error_types", {}),
            }
        )

    elif group_by == "time":
        records = await repo.query_hourly(
            start_time=from_,
            end_time=to,
            granularity=granularity,
            provider=provider,
            model=model,
            llm_type=llm_type,
            call_point=call_point,
        )
        usage_records = [
            {
                "time_bucket": (
                    datetime.fromisoformat(r["time_bucket"])
                    if isinstance(r["time_bucket"], str)
                    else r["time_bucket"]
                ),
                "label": r.get("label", ""),
                "call_point": r.get("call_point", ""),
                "llm_type": r.get("llm_type", ""),
                "provider": r.get("provider", ""),
                "model": r.get("model", ""),
                "call_count": r["call_count"],
                "input_tokens": r.get("input_tokens_sum", 0),
                "output_tokens": r.get("output_tokens_sum", 0),
                "total_tokens": r.get("total_tokens_sum", 0),
                "latency_avg_ms": r["latency_avg_ms"],
                "success_count": r["success_count"],
                "failure_count": r["failure_count"],
            }
            for r in records
        ]
        return success_response(
            {"group_by": "time", "records": usage_records, "total": len(usage_records)}
        )

    elif group_by == "provider":
        records = await repo.get_by_provider(
            start_time=from_,
            end_time=to,
            llm_type=llm_type,
        )
        return success_response(
            {
                "group_by": "provider",
                "records": [
                    {
                        "provider": r["provider"],
                        "call_count": r["call_count"],
                        "input_tokens": r.get("input_tokens", 0),
                        "output_tokens": r.get("output_tokens", 0),
                        "total_tokens": r["total_tokens"],
                        "avg_latency_ms": r.get("avg_latency_ms", 0.0),
                        "success_rate": r.get("success_rate", 1.0),
                    }
                    for r in records
                ],
            }
        )

    elif group_by == "model":
        records = await repo.get_by_model(
            start_time=from_,
            end_time=to,
            provider=provider,
        )
        return success_response(
            {
                "group_by": "model",
                "records": [
                    {
                        "model": r["model"],
                        "provider": r["provider"],
                        "call_count": r["call_count"],
                        "input_tokens": r.get("input_tokens", 0),
                        "output_tokens": r.get("output_tokens", 0),
                        "total_tokens": r["total_tokens"],
                        "avg_latency_ms": r.get("avg_latency_ms", 0.0),
                        "success_rate": r.get("success_rate", 1.0),
                    }
                    for r in records
                ],
            }
        )

    elif group_by == "call_point":
        records = await repo.get_by_call_point(
            start_time=from_,
            end_time=to,
        )
        return success_response(
            {
                "group_by": "call_point",
                "records": [
                    {
                        "call_point": r["call_point"],
                        "call_count": r["call_count"],
                        "total_tokens": r["total_tokens"],
                        "avg_latency_ms": r.get("avg_latency_ms", 0.0),
                        "success_rate": r.get("success_rate", 1.0),
                    }
                    for r in records
                ],
            }
        )

    from fastapi import HTTPException

    raise HTTPException(status_code=400, detail=f"Invalid group_by: {group_by}")
