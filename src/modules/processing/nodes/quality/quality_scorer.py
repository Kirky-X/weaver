# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Rule-based quality scorer — no LLM dependency."""

from __future__ import annotations

from core.observability import get_logger
from modules.processing.pipeline.state import PipelineState

log = get_logger(__name__)

# 5-dimension weights (sum = 1.0)
QUALITY_WEIGHTS = {
    "completeness": 0.30,
    "credibility": 0.25,
    "normativity": 0.20,
    "originality": 0.15,
    "timeliness": 0.10,
}

# Originality: a body at least this long is treated as fully original.
MIN_BODY_LEN_FULL_ORIGINAL = 100
# Timeliness: neutral score when no event_time/publish_time is available.
DEFAULT_TIMELINESS_SCORE = 0.5


class RuleBasedQualityScorerNode:
    """Pipeline node: assess article quality via rules (no LLM).

    Uses 5-dimension weighted scoring:
    - Completeness (30%): Does article have summary, subjects, key_data, impact?
    - Credibility (25%): Does article have credibility scores?
    - Normativity (20%): Does article have category, language, region?
    - Originality (15%): Is article original (not merged)?
    - Timeliness (10%): Does article have event_time or publish_time?

    """

    def __init__(self) -> None:
        """No LLM dependency needed."""

    async def execute(self, state: PipelineState) -> PipelineState:
        """Assess article quality via rules and update state with quality score."""
        if state.get("terminal") or state.get("is_merged"):
            if "quality_score" not in state:
                state["quality_score"] = 0.5
            return state

        score = self._compute_score(state)
        state["quality_score"] = round(score, 2)

        raw_obj = state.get("raw")
        url = raw_obj.url if raw_obj else "unknown"
        log.info(
            "quality_assessed",
            url=url,
            quality_score=state["quality_score"],
        )
        return state

    def _compute_score(self, state: PipelineState) -> float:
        si = state.get("summary_info") or {}

        # 1. Completeness (0.30)
        completeness_fields = [
            bool(si.get("summary")),
            bool(si.get("subjects")),
            bool(si.get("key_data")),
            si.get("has_data") is not None,
        ]
        completeness = sum(completeness_fields) / len(completeness_fields)

        # 2. Credibility (0.25)
        cred = state.get("credibility") or {}
        credibility_fields = [
            cred.get("score") is not None,
            cred.get("source_credibility") is not None,
            cred.get("cross_verification") is not None,
        ]
        credibility = sum(credibility_fields) / len(credibility_fields)

        # 3. Normativity (0.20)
        norm_fields = [
            bool(state.get("category")),
            bool(state.get("language")),
            bool(state.get("region")),
        ]
        normativity = sum(norm_fields) / len(norm_fields)

        # 4. Originality (0.15)
        originality = 0.0
        if not state.get("is_merged"):
            body = (state.get("cleaned") or {}).get("body", "")
            if body and len(body) > MIN_BODY_LEN_FULL_ORIGINAL:
                originality = 1.0
            elif body:
                originality = 0.5
            else:
                originality = 0.3
        else:
            originality = 0.2

        # 5. Timeliness (0.10)
        timeliness = 0.0
        if si.get("event_time") or (state.get("cleaned") or {}).get("publish_time"):
            timeliness = 1.0
        else:
            timeliness = DEFAULT_TIMELINESS_SCORE

        return (
            completeness * QUALITY_WEIGHTS["completeness"]
            + credibility * QUALITY_WEIGHTS["credibility"]
            + normativity * QUALITY_WEIGHTS["normativity"]
            + originality * QUALITY_WEIGHTS["originality"]
            + timeliness * QUALITY_WEIGHTS["timeliness"]
        )
