# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Briefing generator — produce per-category daily briefings (T004).

BriefingGenerator is an independent class (not a pipeline node — see design.md
decision on T004 integration path) that:

1. Fetches articles for a given date filtered by category
   (finance→经济, tech→科技, ai→keyword match, general→no filter).
2. Calls the LLM via CallPoint.BRIEFING to produce a summary.
3. Persists briefing + items to daily_briefings + daily_briefing_items
   via AnalyticsStorage.save_briefing.

Failure handling follows Rule 12 (fail loud):
- LLM failures (AllProvidersFailedError / CircuitOpenError / ValueError)
  degrade gracefully: empty summary, briefing still persisted. Per spec
  R-briefing-002: "LLM 调用失败时：summary 为空，log warning，不抛异常".
- Storage failures raise to the caller (briefing not silently dropped).
  Callers (T010 scheduler / T009 endpoint) decide how to surface to user.
- Empty article list short-circuits before LLM call (save RPM budget).
- Unexpected errors (TypeError, AttributeError, etc.) propagate — these
  are programming bugs that must surface, not be hidden.

Category mapping (Rule 7 — exposed conflict, decision: hybrid):
- articles_core.category uses CategoryType enum (政治/军事/经济/科技/...).
- daily_briefings.category uses finance/tech/ai/general (spec R-briefing-003).
- Mapping is hybrid: enum match for finance/tech, keyword match for ai
  (no direct enum equivalent), no filter for general. The mapping is
  implemented in AnalyticsStorage.fetch_articles_for_briefing (storage
  layer), BriefingGenerator only passes the briefing category through.

TOP_N cap (10):
- daily_briefing_items.rank CHECK constraint is [1, 10]. BriefingGenerator
  caps items at TOP_N=10 to fit the constraint. Items are sorted by score
  descending so the top-10 most relevant articles are kept.
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
    from core.protocols import AnalyticsStorageProtocol

log = get_logger(__name__)

# Daily briefing category namespace (spec R-briefing-003).
# Maps to {finance, tech, ai, general} — distinct from articles_core.category
# which uses CategoryType enum (政治/经济/科技/...).
VALID_BRIEFING_CATEGORIES: frozenset[str] = frozenset({"finance", "tech", "ai", "general"})

# daily_briefing_items.rank CHECK constraint is [1, 10] (misc.py).
# Cap items at 10 to fit the constraint; sort by score desc to keep top-10.
TOP_N_ITEMS: int = 10


class BriefingGenerator:
    """Generate per-category daily briefings.

    Implements:
        BriefingGenerator: Independent generator class (not a pipeline node)
        with LLM failure degradation + storage failure propagation.

    Args:
        llm: Unified LLM client. Must support call_at(CallPoint.BRIEFING, ...).
        budget: Token budget manager (used for articles payload truncation).
        prompt_loader: Prompt template loader. Must have 'briefing.toml'.
        storage: AnalyticsStorageProtocol implementation for fetching
            articles + persisting briefing.
    """

    def __init__(
        self,
        llm: LLMClient,
        budget: TokenBudgetManager,
        prompt_loader: PromptLoader,
        storage: AnalyticsStorageProtocol,
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._prompt_loader = prompt_loader
        self._storage = storage

    async def generate(
        self,
        briefing_date: date,
        category: str | None = None,
    ) -> dict[str, Any]:
        """Generate and persist a daily briefing for the given date + category.

        Args:
            briefing_date: Date to generate briefing for.
            category: Briefing category — one of {finance, tech, ai, general}.
                None is treated as 'general' (no article filter).

        Returns:
            Dict with id/briefing_date/category/summary/items/total_items/
            generated_at. When no articles are found, id is None, summary
            is None, items is [], total_items is 0.

        Raises:
            ValueError: If category is not None and not in
                VALID_BRIEFING_CATEGORIES.
            Exception: Storage failures propagate (Rule 12). LLM failures
                degrade (empty summary) per spec R-briefing-002.
        """
        # Normalize None → 'general' (spec R-briefing-001: None 表示综合).
        normalized_category = category or "general"
        if normalized_category not in VALID_BRIEFING_CATEGORIES:
            raise ValueError(
                f"Invalid category '{normalized_category}'. "
                f"Valid categories: {sorted(VALID_BRIEFING_CATEGORIES)}"
            )

        # Step 1: Fetch articles filtered by category.
        articles = await self._storage.fetch_articles_for_briefing(
            briefing_date=briefing_date,
            category=normalized_category,
        )

        # Empty article list → short-circuit before LLM call (save RPM budget).
        if not articles:
            log.info(
                "briefing_no_articles",
                briefing_date=str(briefing_date),
                category=normalized_category,
            )
            return {
                "id": None,
                "briefing_date": briefing_date,
                "category": normalized_category,
                "summary": None,
                "items": [],
                "total_items": 0,
                "generated_at": datetime.now(UTC),
            }

        # Step 2: Generate summary via LLM (degrade on LLM failure).
        summary = await self._generate_summary(articles, normalized_category)

        # Step 3: Rank + cap items at TOP_N (rank CHECK constraint [1, 10]).
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

        # Step 4: Persist briefing + items (storage failure propagates).
        briefing_id = await self._storage.save_briefing(
            briefing_date=briefing_date,
            category=normalized_category,
            summary=summary,
            items=items,
        )

        log.info(
            "briefing_generated",
            briefing_date=str(briefing_date),
            category=normalized_category,
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

    async def _generate_summary(
        self,
        articles: list[dict[str, Any]],
        category: str,
    ) -> str | None:
        """Call LLM via CallPoint.BRIEFING to summarize articles.

        Returns:
            LLM-generated summary string, or None on LLM failure (degraded).

        Degrades on:
            AllProvidersFailedError: All LLM providers failed (e.g. 429).
            CircuitOpenError: Circuit breaker is open.
            ValueError: Pydantic ValidationError / JSON parse failure.

        Propagates:
            Other Exception (TypeError, AttributeError, etc.): programming
            bugs must surface (Rule 12).
        """
        # Format articles into a single text payload for the LLM.
        articles_text = self._format_articles_for_llm(articles)
        truncated = self._budget.truncate(articles_text, CallPoint.BRIEFING)
        system_prompt = self._prompt_loader.get("briefing", "system")

        try:
            result = await self._llm.call_at(
                CallPoint.BRIEFING,
                {
                    "system_prompt": system_prompt,
                    "articles": truncated,
                    "category": category,
                    "article_count": len(articles),
                },
            )
        except (AllProvidersFailedError, CircuitOpenError, ValueError) as exc:
            log.warning(
                "briefing_llm_failed_degraded",
                exc_type=type(exc).__name__,
                error=str(exc),
                category=category,
                article_count=len(articles),
            )
            return None

        # call_at without output_model returns str. If LLM client returns
        # non-str (programming bug — Rule 12), TypeError propagates to caller.
        if not result:
            return None
        return str(result)

    @staticmethod
    def _format_articles_for_llm(articles: list[dict[str, Any]]) -> str:
        """Format articles list into a single text payload for the LLM.

        Each article is rendered as:
            [N] title (score=X.XX, category=Y)
            body

        Concatenated with double newlines between articles.
        """
        parts: list[str] = []
        for i, article in enumerate(articles, start=1):
            title = article.get("title", "(untitled)")
            body = article.get("body", "")
            score = article.get("score", 0.0)
            category = article.get("category", "unknown")
            parts.append(f"[{i}] {title} (score={score:.2f}, category={category})\n{body}")
        return "\n\n".join(parts)
