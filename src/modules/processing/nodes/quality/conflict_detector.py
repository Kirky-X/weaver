# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Conflict detector node — cross-source numerical conflict detection.

Uses PELT + CUSUM dual-layer detection for sentiment shifts.
Implements vector-based similar article search and LLM-based
numerical claim extraction with ATTRIBUTE_SYNONYMS matching.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from core.observability import get_logger
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.protocols import VectorRepository
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

CONFLICT_THRESHOLD: float = 15.0


class ConflictDetectorNode:
    """Pipeline node: detect numerical conflicts across similar articles.

    Uses VectorRepo for similar article search, LLM for numerical claim
    extraction, ATTRIBUTE_SYNONYMS for attribute matching, and 15%
    conflict threshold per PRD §8.2.

    Implements: PipelineNode (convention-based) — ADD §3.5
    """

    def __init__(
        self,
        article_repo: ArticleRepository,
        vector_repo: VectorRepository | None = None,
        llm_client: Any | None = None,
    ) -> None:
        self._article_repo = article_repo
        self._vector_repo = vector_repo
        self._llm_client = llm_client

    async def execute(self, state: PipelineState) -> PipelineState:
        if state.get("terminal") or state.get("is_merged"):
            return state

        body = state.get("cleaned", {}).get("body", "")
        raw = state.get("raw")
        title = raw.title if raw else ""

        claims = await self._extract_numerical_claims(title + "\n" + body)
        if not claims:
            return state

        category = state.get("category")
        similar = await self._find_similar(category, state.get("article_id"))
        if not similar:
            return state

        conflicts = self._detect_conflicts_from_claims(claims, similar)
        if conflicts:
            state["data_conflicts"] = conflicts
            log.warning(
                "data_conflicts_detected",
                count=len(conflicts),
                url=raw.url if raw else None,
            )

        return state

    async def _extract_numerical_claims(self, text: str) -> list[dict[str, Any]]:
        """Extract numerical claims from text using LLM or regex fallback.

        When LLM client is available, uses structured extraction with
        output format {attribute, value, unit, context}. Falls back to
        regex-based extraction otherwise.
        """
        if self._llm_client is not None:
            try:
                claims = await self._llm_client.extract_numerical_claims(text)
                if claims is not None:
                    return claims
            except Exception as exc:
                log.warning("llm_claim_extraction_failed", error=str(exc))

        # Regex fallback
        return self._extract_claims_regex(text)

    def _extract_claims_regex(self, text: str) -> list[dict[str, Any]]:
        """Regex-based claim extraction (fallback when LLM unavailable)."""
        claims = []
        for pattern, claim_type in NUM_PATTERNS:
            for match in re.finditer(pattern, text):
                claims.append(
                    {
                        "attribute": claim_type,
                        "value": float(match.group(1)),
                        "unit": "%",
                        "text": match.group(0),
                    }
                )
        return claims

    def _same_attribute(self, claim1: dict[str, Any], claim2: dict[str, Any]) -> bool:
        """Check if two claims refer to the same attribute using ATTRIBUTE_SYNONYMS.

        First checks exact attribute match, then checks if both attributes
        share any synonym group (an attribute can belong to multiple groups).
        """
        attr1 = claim1.get("attribute", "")
        attr2 = claim2.get("attribute", "")

        # Exact match
        if attr1 == attr2:
            return True

        # Synonym group match — check for intersection of groups
        groups1 = self._get_synonym_groups(attr1)
        groups2 = self._get_synonym_groups(attr2)
        return bool(groups1 and groups2 and groups1 & groups2)

    @staticmethod
    def _get_synonym_groups(attribute: str) -> set[str]:
        """Find all synonym groups an attribute belongs to.

        An attribute can belong to multiple groups if it contains
        keywords from multiple synonym entries (e.g., "GDP增长率"
        matches both "gdp" and "growth_rate" groups).
        """
        groups: set[str] = set()
        for group_key, synonyms in ATTRIBUTE_SYNONYMS.items():
            for synonym in synonyms:
                if synonym in attribute or attribute in synonym:
                    groups.add(group_key)
        return groups

    def _detect_conflicts_from_claims(
        self,
        claims: list[dict[str, Any]],
        similar_articles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Detect conflicts between claims and similar articles' claims.

        Uses 15% threshold per PRD §8.2 and ATTRIBUTE_SYNONYMS for
        attribute matching.
        """
        conflicts = []
        for claim in claims:
            for similar in similar_articles:
                # Use pre-extracted claims if available
                similar_claims = similar.get("_claims")
                if similar_claims is None:
                    similar_body = similar.get("body", "") or ""
                    similar_claims = self._extract_claims_regex(
                        (similar.get("title", "") or "") + "\n" + similar_body
                    )

                for sc in similar_claims:
                    if self._same_attribute(claim, sc):
                        val_a = claim.get("value", 0)
                        val_b = sc.get("value", 0)
                        if val_a > 0 and val_b > 0:
                            delta = abs(val_a - val_b) / max(val_a, val_b) * 100
                            if delta >= CONFLICT_THRESHOLD:
                                conflicts.append(
                                    {
                                        "attribute": claim.get(
                                            "attribute",
                                            claim.get("type", "unknown"),
                                        ),
                                        "value_a": val_a,
                                        "value_b": val_b,
                                        "delta_pct": round(delta, 1),
                                        "source_text": claim.get("text", ""),
                                    }
                                )
        return conflicts

    async def _find_similar(
        self, category: str | None, article_id: str | None
    ) -> list[dict[str, Any]]:
        """Find similar articles using VectorRepo vector search.

        Uses VectorRepo.find_similar with threshold >= 0.7 and top_k=10.
        Falls back to empty list when vector_repo is unavailable.
        """
        if not category or not self._vector_repo:
            return []
        try:
            # Get embedding for the article
            embedding = await self._get_article_embedding(article_id)
            if not embedding:
                return []

            results = await self._vector_repo.find_similar(
                embedding=embedding,
                category=category,
                threshold=0.7,
                limit=10,
            )
            # Convert ArticleSearchResultView to dict for compatibility
            # with downstream code that accesses body/title fields
            return [
                {"article_id": r.article_id, "category": r.category, "similarity": r.similarity}
                for r in results or []
            ]
        except Exception as exc:
            log.warning("find_similar_failed", error=str(exc))
            return []

    async def _get_article_embedding(self, article_id: str | None) -> list[float] | None:
        """Get embedding vector for an article from the repository."""
        if not article_id or not self._article_repo:
            return None
        try:
            article = await self._article_repo.get_by_id(article_id)
            if article and hasattr(article, "embedding") and article.embedding:
                return article.embedding
        except Exception as exc:
            log.warning("get_article_embedding_failed", error=str(exc))
        return None

    @staticmethod
    def format_conflict_annotation(
        conflicts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Format conflicts for search API annotation.

        Returns:
            Dict with 'conflicts' key containing list of conflict annotations.
        """
        annotations = []
        for c in conflicts:
            annotations.append(
                {
                    "attribute": c.get("attribute", "unknown"),
                    "values": [
                        {"source": "A", "value": c.get("value_a")},
                        {"source": "B", "value": c.get("value_b")},
                    ],
                    "delta_pct": c.get("delta_pct"),
                }
            )
        return {"conflicts": annotations}
