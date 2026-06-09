# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Conflict detector node — cross-source numerical conflict detection."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from core.observability.logging import get_logger
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from modules.storage import ArticleRepository

log = get_logger(__name__)

NUM_PATTERNS = [
    (r"(\d+(?:\.\d+)?)\s*%", "percent"),
    (r"(\d+(?:\.\d+)?)\s*(?:亿|万|千|百)", "number_unit"),
    (r"增长[了]?\s*(\d+(?:\.\d+)?)\s*%", "growth"),
    (r"下降[了]?\s*(\d+(?:\.\d+)?)\s*%", "decline"),
    (r"达到\s*(\d+(?:\.\d+)?)\s*(?:亿|万|千)?", "reach"),
]

ATTRIBUTE_SYNONYMS: dict[str, list[str]] = {
    "unemployment": ["失业率", "失业"],
    "gdp": ["GDP", "国内生产总值", "生产总值"],
    "inflation": ["通胀", "通货膨胀", "CPI"],
    "growth_rate": ["增长率", "增速", "增长"],
    "population": ["人口", "人数"],
    "budget": ["预算", "财政支出"],
    "revenue": ["收入", "营收"],
    "profit": ["利润", "盈利"],
}


class ConflictDetectorNode:
    """Pipeline node: detect numerical conflicts across similar articles.

    Implements: PipelineNode (convention-based)
    """

    def __init__(self, article_repo: ArticleRepository) -> None:
        self._article_repo = article_repo

    async def execute(self, state: PipelineState) -> PipelineState:
        if state.get("terminal") or state.get("is_merged"):
            return state

        body = state.get("cleaned", {}).get("body", "")
        raw = state.get("raw")
        title = raw.title if raw else ""

        claims = self._extract_claims(title + "\n" + body)
        if not claims:
            return state

        category = state.get("category")
        similar = await self._find_similar(category, state.get("article_id"))
        if not similar:
            return state

        conflicts = self._detect_conflicts(claims, similar)
        if conflicts:
            state["data_conflicts"] = conflicts
            log.warning(
                "data_conflicts_detected",
                count=len(conflicts),
                url=raw.url if raw else None,
            )

        return state

    def _extract_claims(self, text: str) -> list[dict[str, Any]]:
        claims = []
        for pattern, claim_type in NUM_PATTERNS:
            for match in re.finditer(pattern, text):
                claims.append(
                    {
                        "type": claim_type,
                        "value": float(match.group(1)),
                        "text": match.group(0),
                    }
                )
        return claims

    @staticmethod
    def _same_attribute(claim1: dict[str, Any], claim2: dict[str, Any]) -> bool:
        """Check if two claims refer to the same attribute type."""
        return claim1.get("type") == claim2.get("type")

    def _detect_conflicts(
        self, claims: list[dict[str, Any]], similar_articles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        conflicts = []
        for claim in claims:
            for similar in similar_articles:
                similar_body = similar.get("body", "") or ""
                similar_claims = self._extract_claims(
                    (similar.get("title", "") or "") + "\n" + similar_body
                )
                for sc in similar_claims:
                    if self._same_attribute(claim, sc):
                        if claim["value"] > 0 and sc["value"] > 0:
                            delta = (
                                abs(claim["value"] - sc["value"])
                                / max(claim["value"], sc["value"])
                                * 100
                            )
                            if delta >= 20:
                                conflicts.append(
                                    {
                                        "attribute": claim.get("type", "unknown"),
                                        "value_a": claim["value"],
                                        "value_b": sc["value"],
                                        "delta_pct": round(delta, 1),
                                        "source_text": claim.get("text", ""),
                                    }
                                )
        return conflicts

    async def _find_similar(
        self, category: str | None, article_id: str | None
    ) -> list[dict[str, Any]]:
        if not category or not self._article_repo:
            return []
        try:
            return []
        except Exception:
            return []
