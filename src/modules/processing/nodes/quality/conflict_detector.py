# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Conflict detector node — cross-source numerical conflict detection.

Uses PELT + CUSUM dual-layer detection for sentiment shifts.
Implements vector-based similar article search and LLM-based
numerical claim extraction with ATTRIBUTE_SYNONYMS matching.
"""

from __future__ import annotations

import json
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
    conflict threshold.

    Implements: PipelineNode (convention-based)
    """

    def __init__(
        self,
        article_repo: ArticleRepository,
        vector_repo: VectorRepository | None = None,
        llm_client: Any | None = None,
        similarity_threshold: float = 0.7,
        similar_limit: int = 10,
    ) -> None:
        self._article_repo = article_repo
        self._vector_repo = vector_repo
        self._llm_client = llm_client
        self._similarity_threshold = similarity_threshold
        self._similar_limit = similar_limit

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

        # ArticleSearchResultView carries only ids/scores — fetch bodies so
        # regex claim extraction has real content to work on.
        similar = await self._enrich_with_bodies(similar)

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
                result = await self._llm_client.call_at(
                    "claim_extraction",
                    {"text": text[:4000]},
                )
                # call_at may return a string (raw LLM response); parse JSON if needed
                if isinstance(result, str):
                    try:
                        result = json.loads(result)
                    except (json.JSONDecodeError, TypeError):
                        log.warning(
                            "claim_extraction_response_not_json",
                            response_preview=result[:200],
                        )
                        return self._extract_claims_regex(text)

                # Result may be a list of claims directly, or a dict with a "claims" key
                if isinstance(result, list):
                    return result
                if isinstance(result, dict) and "claims" in result:
                    return result["claims"]
                if isinstance(result, dict):
                    return [result]

                return self._extract_claims_regex(text)
            except Exception as exc:
                log.warning("llm_claim_extraction_failed", error=str(exc))

        # Regex fallback
        return self._extract_claims_regex(text)

    def _extract_claims_regex(self, text: str) -> list[dict[str, Any]]:
        """Regex-based claim extraction (fallback when LLM unavailable)."""
        claims: list[dict[str, Any]] = []
        for pattern, claim_type in NUM_PATTERNS:
            for match in re.finditer(pattern, text):
                claims.append(
                    {
                        "attribute": claim_type,
                        "value": float(match.group(1)),
                        "unit": self._unit_for(claim_type, match.group(0)),
                        "text": match.group(0),
                    }
                )
        return claims

    @staticmethod
    def _unit_for(claim_type: str, full_match: str) -> str:
        """Extract the real unit from the matched text for a claim type.

        Hardcoding "%" for every pattern misrepresents number/reach claims
        (e.g. "3亿" has unit 亿, not %), causing cross-scale comparisons.
        """
        if claim_type in ("percent", "growth", "decline"):
            return "%"
        if claim_type in ("number_unit", "reach"):
            for unit in ("亿", "万", "千", "百"):
                if unit in full_match:
                    return unit
            return ""
        return ""

    def _same_attribute(self, claim1: dict[str, Any], claim2: dict[str, Any]) -> bool:
        """Check if two claims refer to the same attribute using ATTRIBUTE_SYNONYMS.

        First checks exact attribute match, then checks if both attributes
        share any synonym group (an attribute can belong to multiple groups).
        """
        attr1 = claim1.get("attribute", "")
        attr2 = claim2.get("attribute", "")

        # Exact match (non-empty — two empty/missing attributes must not
        # be treated as the same attribute).
        if attr1 and attr1 == attr2:
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
        # Empty/missing attribute would match every group via the
        # always-true `"" in synonym` check, producing false-positive
        # conflicts between unrelated claims.
        if not attribute:
            return set()
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

        Uses 15% threshold and ATTRIBUTE_SYNONYMS for
        attribute matching.
        """
        conflicts = []
        for claim in claims:
            for similar in similar_articles:
                # Use pre-extracted claims if available
                similar_claims = similar.get("_claims")
                if similar_claims is None:
                    similar_title = similar.get("title", "") or ""
                    similar_body = similar.get("body", "") or ""
                    if not similar_title and not similar_body:
                        log.debug(
                            "similar_article_missing_content",
                            article_id=similar.get("article_id"),
                        )
                    similar_claims = self._extract_claims_regex(similar_title + "\n" + similar_body)

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
                threshold=self._similarity_threshold,
                limit=self._similar_limit,
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

    async def _enrich_with_bodies(self, similar: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Batch-fetch article bodies for similar articles.

        ``ArticleSearchResultView`` carries only ids/scores; without this
        step ``_detect_conflicts_from_claims`` would run regex extraction
        on empty strings and never produce conflicts. Fetch failures are
        logged and leave entries without body (detection degrades to
        no-op for those entries rather than raising).
        """
        pending_ids = [s["article_id"] for s in similar if not s.get("body")]
        if not pending_ids or not self._article_repo:
            return similar
        if not hasattr(self._article_repo, "fetch_bodies_by_pg_ids"):
            return similar
        try:
            bodies = await self._article_repo.fetch_bodies_by_pg_ids(pending_ids)
        except Exception as exc:
            log.warning(
                "fetch_similar_bodies_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
                pending_count=len(pending_ids),
            )
            return similar
        for s in similar:
            body = bodies.get(s["article_id"])
            if body:
                s["body"] = body
        return similar

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
