# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Narrative briefing generator — produces briefings from NarrativeNode framing (T020 / R-briefing-007).

NarrativeBriefingGenerator is the narrative-mode counterpart of BriefingGenerator
(T004). Instead of feeding raw article text to the LLM, it aggregates
NarrativeNode framing dimensions (source_bias/frame/tone/emphasis) across
multiple articles and asks the LLM to produce a narrative-style summary that
reflects how different sources framed the same topic.

Spec R-briefing-007 acceptance:
- Query NarrativeNode (HAS_NARRATIVE relationship from EventNode, which is
  linked to Article via HAS_EVENT).
- Filter articles by category (delegated to storage.fetch_articles_for_briefing
  to reuse the existing category mapping — Rule 8: no duplicated logic).
- Call LLM aggregating multiple NarrativeNode framing dimensions.
- Raise InsufficientNarrativeError when NarrativeNode count < 3.

Cross-database compatibility (Rule — Neo4j + LadybugDB):
    NarrativeNode schema fields are identical across Neo4j and LadybugDB
    (ladybug_schema.py: source_bias/frame/tone/emphasis/created_at/updated_at).
    The query uses standard Cypher MATCH pattern that both databases support.
    LadybugDB pool is detected via ``pool.database_type == 'ladybug'`` for
    future cross-DB branches (currently the query is identical).

Constructor injection (Rule — Protocol type, not concrete class):
    ``__init__(self, graph_pool: GraphPool, llm: LLMClient, budget: TokenBudgetManager,
    prompt_loader: PromptLoader, storage: AnalyticsStorageProtocol)``
    accepts any pool implementing GraphPool (Neo4jPool / LadybugPool) and any
    storage implementing AnalyticsStorageProtocol.

Failure handling (Rule 12 — fail loud):
    - LLM failures (AllProvidersFailedError / CircuitOpenError / ValueError)
      degrade gracefully: empty summary, briefing still persisted (R-briefing-002
      best-effort contract, consistent with BriefingGenerator).
    - Storage failures (save_briefing) propagate to caller.
    - Graph DB errors propagate (Rule 12).
    - InsufficientNarrativeError is the explicit "no degradation" signal —
      the caller (DailyBriefingService T021) catches it to fall back to
      template mode. This is NOT an error to swallow; it carries enough
      context (narrative_count, threshold, briefing_date, category, reason)
      for the caller to log a meaningful warning.

Return shape parity with BriefingGenerator.generate():
    Same dict keys (id/briefing_date/category/summary/items/total_items/
    generated_at) — allows DailyBriefingService.generate_briefing() to use
    either generator interchangeably (Rule 11: convention over novelty).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from core.llm.resilience.circuit_breaker import CircuitOpenError
from core.llm.resilience.pool import AllProvidersFailedError
from core.llm.types import CallPoint
from core.observability import get_logger

if TYPE_CHECKING:
    from core.llm.client import LLMClient
    from core.llm.config.token_budget import TokenBudgetManager
    from core.prompt.loader import PromptLoader
    from core.protocols import AnalyticsStorageProtocol, GraphPool

log = get_logger(__name__)

# Spec R-briefing-003: 4 briefing categories (mirrors BriefingGenerator).
VALID_BRIEFING_CATEGORIES: frozenset[str] = frozenset({"finance", "tech", "ai", "general"})

# Spec R-briefing-007: minimum NarrativeNode count to produce narrative briefing.
# Below this threshold, raise InsufficientNarrativeError so the caller (T021)
# can degrade to template mode.
MIN_NARRATIVE_COUNT: int = 3

# daily_briefing_items.rank CHECK constraint is [1, 10] (misc.py).
# Same cap as BriefingGenerator — keep top-10 articles by score descending.
TOP_N_ITEMS: int = 10


class InsufficientNarrativeError(Exception):
    """Raised when NarrativeNode count is below the narrative-mode threshold.

    Spec R-briefing-007: NarrativeBriefingGenerator requires at least 3
    NarrativeNodes to produce a narrative-style briefing. Below this threshold,
    the generator raises this exception so the caller (DailyBriefingService
    T021) can degrade to template mode (BriefingGenerator).

    This is NOT a programming bug — it signals data insufficiency. The caller
    is expected to catch this exception (spec R-briefing-008: 降级为模板模式,
    log warning 含原因). Propagating it would surface as a 500 to the API
    caller, which is incorrect — degradation is the intended behavior.

    Attributes:
        narrative_count: Actual NarrativeNode count found.
        threshold: Minimum required count (3, per spec).
        briefing_date: Date the briefing was requested for.
        category: Briefing category (finance/tech/ai/general).
        reason: Human-readable explanation of why the threshold was not met.
    """

    def __init__(
        self,
        *,
        narrative_count: int,
        threshold: int,
        briefing_date: date,
        category: str,
        reason: str,
    ) -> None:
        self.narrative_count = narrative_count
        self.threshold = threshold
        self.briefing_date = briefing_date
        self.category = category
        self.reason = reason
        super().__init__(
            f"Insufficient NarrativeNode count for {category} briefing on "
            f"{briefing_date}: {narrative_count} < {threshold} ({reason})"
        )


class NarrativeBriefingGenerator:
    """Generate narrative-style briefings from NarrativeNode framing (R-briefing-007).

    Implements:
        NarrativeBriefingGenerator: Narrative-mode briefing generator with
        LLM failure degradation + InsufficientNarrativeError threshold.

    Unlike BriefingGenerator (template mode), this generator:
    1. Fetches articles for date+category (reuses storage logic — Rule 8).
    2. Queries NarrativeNode for each article via graph DB (single batch query
       with ``WHERE e.id IN $article_ids``).
    3. Raises InsufficientNarrativeError when total NarrativeNode count < 3.
    4. Aggregates NarrativeNode framing (source_bias/frame/tone/emphasis) per
       article and injects it into the LLM payload alongside article text.
    5. Calls LLM via CallPoint.BRIEFING (same CallPoint as BriefingGenerator —
       Rule 11: convention over novelty).
    6. Persists via storage.save_briefing (same as BriefingGenerator — return
       shape parity for DailyBriefingService interchangeability).

    Args:
        graph_pool: GraphPool implementation (Neo4jPool or LadybugPool).
            Used via ``pool.execute_query()`` for NarrativeNode queries.
        llm: Unified LLM client. Must support call_at(CallPoint.BRIEFING, ...).
        budget: Token budget manager (used for narrative payload truncation).
        prompt_loader: Prompt template loader. Must have 'briefing.toml'.
        storage: AnalyticsStorageProtocol implementation for fetching
            articles (with category mapping) + persisting briefing.

    Raises:
        TypeError: If graph_pool does not implement GraphPool (delegated
            to runtime_checkable Protocol check at call site).
    """

    def __init__(
        self,
        graph_pool: GraphPool,
        llm: LLMClient,
        budget: TokenBudgetManager,
        prompt_loader: PromptLoader,
        storage: AnalyticsStorageProtocol,
    ) -> None:
        self._pool = graph_pool
        self._llm = llm
        self._budget = budget
        self._prompt_loader = prompt_loader
        self._storage = storage
        # Detect LadybugDB for cross-database query branches (temporal.py pattern).
        # GraphPool Protocol does not declare database_type, but both Neo4jPool
        # and LadybugPool expose it (concrete impl detail). getattr fallback
        # keeps the Protocol pure while enabling future branches.
        self._is_ladybug = getattr(graph_pool, "database_type", None) == "ladybug"

    async def generate(
        self,
        briefing_date: date,
        category: str | None = None,
    ) -> dict[str, Any]:
        """Generate and persist a narrative-style daily briefing.

        Args:
            briefing_date: Date to generate briefing for.
            category: Briefing category — one of {finance, tech, ai, general}.
                None is treated as 'general' (no article filter).

        Returns:
            Dict with id/briefing_date/category/summary/items/total_items/
            generated_at. Same shape as BriefingGenerator.generate() —
            allows DailyBriefingService to use either generator.

        Raises:
            ValueError: If category is not None and not in
                VALID_BRIEFING_CATEGORIES.
            InsufficientNarrativeError: If NarrativeNode count < 3
                (spec R-briefing-007). Caller (T021) catches this to degrade.
            Exception: Graph DB errors and storage failures propagate
                (Rule 12). LLM failures degrade to empty summary.
        """
        # Normalize None → 'general' (spec R-briefing-001: None 表示综合).
        normalized_category = category or "general"
        if normalized_category not in VALID_BRIEFING_CATEGORIES:
            raise ValueError(
                f"Invalid category '{normalized_category}'. "
                f"Valid categories: {sorted(VALID_BRIEFING_CATEGORIES)}"
            )

        # Step 1: Fetch articles filtered by category (reuses storage logic).
        # BriefingGenerator's category mapping decision (Rule 7 — exposed
        # conflict, hybrid mapping) is implemented in storage; we do NOT
        # duplicate it here (Rule 8: reuse existing implementations).
        articles = await self._storage.fetch_articles_for_briefing(
            briefing_date=briefing_date,
            category=normalized_category,
        )

        if not articles:
            raise InsufficientNarrativeError(
                narrative_count=0,
                threshold=MIN_NARRATIVE_COUNT,
                briefing_date=briefing_date,
                category=normalized_category,
                reason="no articles found for date+category",
            )

        # Step 2: Query NarrativeNode for all articles in one batch.
        # Graph path: (n:NarrativeNode)<-[:HAS_NARRATIVE]-(e:EventNode)
        # WHERE e.id IN $article_ids (EventNode.id = article_id per
        # LadybugWriter.merge_narrative and Neo4jWriter.merge_narrative).
        article_ids = [
            a.get("article_id") or a.get("id")
            for a in articles
            if a.get("article_id") or a.get("id")
        ]
        narratives = await self._query_narratives_for_articles(article_ids)

        # Step 3: Check threshold (R-briefing-007).
        if len(narratives) < MIN_NARRATIVE_COUNT:
            log.info(
                "narrative_briefing_insufficient_data",
                briefing_date=str(briefing_date),
                category=normalized_category,
                narrative_count=len(narratives),
                threshold=MIN_NARRATIVE_COUNT,
                article_count=len(articles),
            )
            raise InsufficientNarrativeError(
                narrative_count=len(narratives),
                threshold=MIN_NARRATIVE_COUNT,
                briefing_date=briefing_date,
                category=normalized_category,
                reason="insufficient NarrativeNode count",
            )

        # Step 4: Aggregate narratives per article (for LLM payload).
        narratives_by_article = self._group_narratives_by_article(narratives)

        # Step 5: Generate summary via LLM (degrade on LLM failure).
        summary = await self._generate_narrative_summary(
            articles=articles,
            narratives_by_article=narratives_by_article,
            category=normalized_category,
        )

        # Step 6: Rank + cap items at TOP_N (rank CHECK constraint [1, 10]).
        # Same logic as BriefingGenerator — return shape parity (Rule 11).
        ranked_articles = sorted(articles, key=lambda a: a.get("score", 0.0), reverse=True)[
            :TOP_N_ITEMS
        ]
        items = [
            {
                "article_id": a.get("article_id") or a.get("id"),
                "rank": rank + 1,
                "score": a.get("score", 0.0),
                "category": a.get("category"),
                "reason": a.get("reason"),
            }
            for rank, a in enumerate(ranked_articles)
        ]

        # Step 7: Persist briefing + items (storage failure propagates).
        briefing_id = await self._storage.save_briefing(
            briefing_date=briefing_date,
            category=normalized_category,
            summary=summary,
            items=items,
        )

        log.info(
            "narrative_briefing_generated",
            briefing_date=str(briefing_date),
            category=normalized_category,
            narrative_count=len(narratives),
            article_count=len(articles),
            total_items=len(items),
            has_summary=summary is not None,
            briefing_id=briefing_id,
        )

        return {
            "id": briefing_id,
            "briefing_date": briefing_date,
            "category": normalized_category,
            "summary": summary,
            "items": items,
            "total_items": len(items),
            "generated_at": datetime.now(UTC),
        }

    async def _query_narratives_for_articles(
        self,
        article_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Query NarrativeNode rows for a batch of article IDs.

        Graph path: (n:NarrativeNode)<-[:HAS_NARRATIVE]-(e:EventNode)
        WHERE e.id IN $article_ids.

        LadybugWriter.merge_narrative and Neo4jWriter.merge_narrative both
        create EventNode with id=article_id and link NarrativeNode via
        HAS_NARRATIVE. The query returns one row per (article, narrative)
        pair, including the 4 framing dimensions.

        Args:
            article_ids: List of article UUID strings (EventNode.id values).

        Returns:
            List of dict rows with article_id + source_bias/frame/tone/emphasis.
            Empty list if no NarrativeNodes found (caller raises
            InsufficientNarrativeError).

        Raises:
            Exception: On graph DB error (Rule 12 — propagate).
        """
        if not article_ids:
            return []

        query = """
        MATCH (n:NarrativeNode)<-[:HAS_NARRATIVE]-(e:EventNode)
        WHERE e.id IN $article_ids
        RETURN e.id AS article_id,
               n.source_bias AS source_bias,
               n.frame AS frame,
               n.tone AS tone,
               n.emphasis AS emphasis
        """
        params: dict[str, Any] = {"article_ids": article_ids}
        return await self._pool.execute_query(query, params)

    @staticmethod
    def _group_narratives_by_article(
        narratives: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Group NarrativeNode rows by article_id for LLM payload injection.

        Args:
            narratives: Flat list of narrative rows (one per article-narrative pair).

        Returns:
            Dict mapping article_id → list of narrative dicts (each with
            source_bias/frame/tone/emphasis). Articles with no narratives
            are absent from the dict (caller handles missing keys).
        """
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in narratives:
            article_id = row.get("article_id")
            if not article_id:
                continue
            grouped.setdefault(article_id, []).append(
                {
                    "source_bias": row.get("source_bias"),
                    "frame": row.get("frame"),
                    "tone": row.get("tone"),
                    "emphasis": row.get("emphasis"),
                }
            )
        return grouped

    async def _generate_narrative_summary(
        self,
        *,
        articles: list[dict[str, Any]],
        narratives_by_article: dict[str, list[dict[str, Any]]],
        category: str,
    ) -> str | None:
        """Call LLM via CallPoint.BRIEFING with aggregated narrative framing.

        Builds a payload that interleaves article text with per-article
        narrative framing (source_bias/frame/tone/emphasis). The LLM is
        asked to produce a narrative-style summary reflecting how sources
        framed the topic.

        Degrades on:
            AllProvidersFailedError: All LLM providers failed (e.g. 429).
            CircuitOpenError: Circuit breaker is open.
            ValueError: Pydantic ValidationError / JSON parse failure.

        Propagates:
            Other Exception (TypeError, AttributeError, etc.): programming
            bugs must surface (Rule 12).

        Args:
            articles: List of article dicts (title/body/score/category).
            narratives_by_article: Dict mapping article_id → list of
                NarrativeNode framing dicts.
            category: Briefing category (for category-specific prompt).

        Returns:
            LLM-generated narrative summary string, or None on LLM failure.
        """
        # Build narrative-aware payload text.
        narrative_text = self._format_articles_with_narratives(
            articles=articles,
            narratives_by_article=narratives_by_article,
        )
        truncated = self._budget.truncate(narrative_text, CallPoint.BRIEFING)
        system_prompt = self._prompt_loader.get("briefing", "system")

        # Payload includes both the article text and the structured narrative
        # framing data. The LLM can use either or both to produce the
        # narrative-style summary.
        payload = {
            "system_prompt": system_prompt,
            "articles": truncated,
            "category": category,
            "article_count": len(articles),
            "narrative_framing": narratives_by_article,
            "narrative_mode": True,
        }

        try:
            result = await self._llm.call_at(CallPoint.BRIEFING, payload)
        except (AllProvidersFailedError, CircuitOpenError, ValueError) as exc:
            log.warning(
                "narrative_briefing_llm_failed_degraded",
                exc_type=type(exc).__name__,
                error=str(exc),
                category=category,
                article_count=len(articles),
            )
            return None

        if not result:
            return None
        return str(result)

    @staticmethod
    def _format_articles_with_narratives(
        *,
        articles: list[dict[str, Any]],
        narratives_by_article: dict[str, list[dict[str, Any]]],
    ) -> str:
        """Format articles + narrative framing into a single LLM payload text.

        Each article is rendered as:
            [N] title (score=X.XX, category=Y)
            body
            [Narrative Framing]
            - Source bias: <bias1>, <bias2>, ...
            - Frame: <frame1>, <frame2>, ...
            - Tone: <tone1>, <tone2>, ...
            - Emphasis: <emphasis1>, <emphasis2>, ...

        Articles without narratives are still included (body only, no
        framing section) — they contribute to the article context but do
        not count toward the narrative threshold (already checked in
        ``generate()``).

        Concatenated with double newlines between articles.
        """
        parts: list[str] = []
        for i, article in enumerate(articles, start=1):
            title = article.get("title", "(untitled)")
            body = article.get("body", "")
            score = article.get("score", 0.0)
            category = article.get("category", "unknown")
            article_id = article.get("article_id") or article.get("id")

            section = f"[{i}] {title} (score={score:.2f}, category={category})\n{body}"

            # Append narrative framing if available for this article.
            framings = narratives_by_article.get(article_id, []) if article_id else []
            if framings:
                bias_list = [f.get("source_bias") for f in framings if f.get("source_bias")]
                frame_list = [f.get("frame") for f in framings if f.get("frame")]
                tone_list = [f.get("tone") for f in framings if f.get("tone")]
                emphasis_list = [f.get("emphasis") for f in framings if f.get("emphasis")]
                section += "\n[Narrative Framing]"
                if bias_list:
                    section += f"\n- Source bias: {', '.join(bias_list)}"
                if frame_list:
                    section += f"\n- Frame: {', '.join(frame_list)}"
                if tone_list:
                    section += f"\n- Tone: {', '.join(tone_list)}"
                if emphasis_list:
                    section += f"\n- Emphasis: {', '.join(emphasis_list)}"

            parts.append(section)
        return "\n\n".join(parts)


__all__ = [
    "MIN_NARRATIVE_COUNT",
    "InsufficientNarrativeError",
    "NarrativeBriefingGenerator",
]
