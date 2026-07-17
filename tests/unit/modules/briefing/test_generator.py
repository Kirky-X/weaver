# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for BriefingGenerator (T004).

BriefingGenerator is an independent class (not a pipeline node — user decision
on T004 integration path) that:
1. Fetches articles for a given date filtered by category
   (finance→经济, tech→科技, ai→keyword match, general→no filter).
2. Calls the LLM via CallPoint.BRIEFING to produce a summary.
3. Persists briefing + items to daily_briefings + daily_briefing_items
   via AnalyticsStorage.save_briefing.

Failure handling follows Rule 12 (fail loud):
- LLM failures degrade gracefully (empty summary, briefing still persisted).
- Storage failures raise to the caller (briefing not persisted silently).
- Empty article list short-circuits before LLM call (no wasted RPM budget).

Category mapping rationale (Rule 7 — exposed conflict, decision: hybrid):
- articles_core.category uses CategoryType enum (政治/军事/经济/科技/...).
- daily_briefings.category uses finance/tech/ai/general (spec R-briefing-003).
- Mapping is hybrid: enum match for finance/tech, keyword match for ai
  (no direct enum equivalent), no filter for general.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from core.llm.resilience.circuit_breaker import CircuitOpenError
from core.llm.resilience.pool import AllProvidersFailedError
from core.llm.types import CallPoint
from modules.briefing.generator import BriefingGenerator


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    return AsyncMock()


@pytest.fixture
def mock_budget():
    """Mock token budget manager — truncate is a passthrough MagicMock (assertable)."""
    budget = MagicMock()
    budget.truncate = MagicMock(side_effect=lambda text, call_point: text)
    return budget


@pytest.fixture
def mock_prompt_loader():
    """Mock prompt loader — returns canned templates."""
    loader = MagicMock()
    loader.get = MagicMock(return_value="Briefing system prompt")
    loader.get_version = MagicMock(return_value="1.0.0")
    return loader


@pytest.fixture
def mock_storage():
    """Mock AnalyticsStorage — save_briefing returns the new briefing id."""
    storage = AsyncMock()
    storage.save_briefing = AsyncMock(return_value=42)
    storage.fetch_articles_for_briefing = AsyncMock(return_value=[])
    return storage


@pytest.fixture
def generator(mock_llm, mock_budget, mock_prompt_loader, mock_storage):
    """Create BriefingGenerator with all mocks injected."""
    return BriefingGenerator(
        llm=mock_llm,
        budget=mock_budget,
        prompt_loader=mock_prompt_loader,
        storage=mock_storage,
    )


def _make_article(
    *,
    article_id: str | None = None,
    title: str = "Sample title",
    body: str = "Sample body content.",
    category: str | None = None,
    score: float = 0.7,
    sentiment_score: float | None = 0.3,
    credibility_score: float | None = 0.8,
    quality_score: float | None = 0.6,
    publish_time: datetime | None = None,
) -> dict:
    """Build a normalized article dict as returned by fetch_articles_for_briefing."""
    return {
        "article_id": article_id or str(uuid4()),
        "title": title,
        "body": body,
        "category": category,
        "score": score,
        "sentiment_score": sentiment_score,
        "credibility_score": credibility_score,
        "quality_score": quality_score,
        "publish_time": publish_time or datetime.now(UTC),
    }


class TestBriefingGeneratorCategoryFilter:
    """Verify BriefingGenerator routes category to storage filter correctly."""

    @pytest.mark.asyncio
    async def test_generate_finance_passes_economy_enum_to_storage(self, generator, mock_storage):
        """finance category maps to articles_core.category == '经济'."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(category="经济", title="Stock market rally")
        ]
        mock_llm_call = AsyncMock(return_value="Finance summary")
        generator._llm.call_at = mock_llm_call  # type: ignore[attr-defined]

        await generator.generate(date(2026, 7, 17), category="finance")

        mock_storage.fetch_articles_for_briefing.assert_awaited_once()
        call_kwargs = mock_storage.fetch_articles_for_briefing.call_args.kwargs
        assert call_kwargs["briefing_date"] == date(2026, 7, 17)
        assert call_kwargs["category"] == "finance"

    @pytest.mark.asyncio
    async def test_generate_tech_passes_tech_enum_to_storage(self, generator, mock_storage):
        """tech category maps to articles_core.category == '科技'."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(category="科技", title="New chip released")
        ]
        generator._llm.call_at = AsyncMock(return_value="Tech summary")  # type: ignore[attr-defined]

        await generator.generate(date(2026, 7, 17), category="tech")

        call_kwargs = mock_storage.fetch_articles_for_briefing.call_args.kwargs
        assert call_kwargs["category"] == "tech"

    @pytest.mark.asyncio
    async def test_generate_ai_passes_ai_category_to_storage(self, generator, mock_storage):
        """ai category is passed through (keyword filter applied at storage layer)."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(category="科技", title="OpenAI releases GPT-5")
        ]
        generator._llm.call_at = AsyncMock(return_value="AI summary")  # type: ignore[attr-defined]

        await generator.generate(date(2026, 7, 17), category="ai")

        call_kwargs = mock_storage.fetch_articles_for_briefing.call_args.kwargs
        assert call_kwargs["category"] == "ai"

    @pytest.mark.asyncio
    async def test_generate_general_passes_none_category_to_storage(self, generator, mock_storage):
        """general category (or None) means no category filter."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(category="经济"),
            _make_article(category="科技"),
        ]
        generator._llm.call_at = AsyncMock(return_value="General summary")  # type: ignore[attr-defined]

        await generator.generate(date(2026, 7, 17), category="general")

        call_kwargs = mock_storage.fetch_articles_for_briefing.call_args.kwargs
        assert call_kwargs["category"] == "general"

    @pytest.mark.asyncio
    async def test_generate_none_category_treated_as_general(self, generator, mock_storage):
        """None category is treated as 'general' (no filter)."""
        mock_storage.fetch_articles_for_briefing.return_value = []
        generator._llm.call_at = AsyncMock(return_value="General summary")  # type: ignore[attr-defined]

        await generator.generate(date(2026, 7, 17), category=None)

        call_kwargs = mock_storage.fetch_articles_for_briefing.call_args.kwargs
        assert call_kwargs["category"] == "general"

    @pytest.mark.asyncio
    async def test_generate_invalid_category_raises_value_error(self, generator, mock_storage):
        """Invalid category must raise ValueError (Rule 12 — fail loud, no silent fallback)."""
        with pytest.raises(ValueError, match="Invalid category"):
            await generator.generate(date(2026, 7, 17), category="sports")


class TestBriefingGeneratorLLMCall:
    """Verify BriefingGenerator calls LLM via CallPoint.BRIEFING correctly."""

    @pytest.mark.asyncio
    async def test_generate_calls_llm_with_briefing_call_point(
        self, generator, mock_llm, mock_storage
    ):
        """LLM call uses CallPoint.BRIEFING (added in T004)."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(title="Article 1"),
            _make_article(title="Article 2"),
        ]
        mock_llm.call_at = AsyncMock(return_value="Briefing summary text")

        await generator.generate(date(2026, 7, 17), category="general")

        mock_llm.call_at.assert_awaited_once()
        call_args = mock_llm.call_at.call_args
        assert call_args.args[0] == CallPoint.BRIEFING

    @pytest.mark.asyncio
    async def test_generate_truncates_articles_via_budget(
        self, generator, mock_llm, mock_budget, mock_storage
    ):
        """Articles payload is truncated via budget manager before LLM call."""
        articles = [_make_article(title=f"Article {i}") for i in range(20)]
        mock_storage.fetch_articles_for_briefing.return_value = articles
        mock_llm.call_at = AsyncMock(return_value="Summary")

        await generator.generate(date(2026, 7, 17), category="general")

        # budget.truncate is called with the formatted articles payload
        mock_budget.truncate.assert_called_once()
        truncate_args = mock_budget.truncate.call_args
        assert truncate_args.args[1] == CallPoint.BRIEFING

    @pytest.mark.asyncio
    async def test_generate_uses_prompt_loader_for_system_prompt(
        self, generator, mock_llm, mock_prompt_loader, mock_storage
    ):
        """System prompt is loaded via prompt_loader.get('briefing', 'system')."""
        mock_storage.fetch_articles_for_briefing.return_value = [_make_article(title="Article 1")]
        mock_llm.call_at = AsyncMock(return_value="Summary")

        await generator.generate(date(2026, 7, 17), category="general")

        mock_prompt_loader.get.assert_called_with("briefing", "system")


class TestBriefingGeneratorPersistence:
    """Verify BriefingGenerator persists briefing + items via storage."""

    @pytest.mark.asyncio
    async def test_generate_persists_briefing_with_summary(self, generator, mock_llm, mock_storage):
        """Successful generation persists briefing with LLM-generated summary."""
        articles = [
            _make_article(article_id="art-1", title="A1", score=0.9),
            _make_article(article_id="art-2", title="A2", score=0.8),
        ]
        mock_storage.fetch_articles_for_briefing.return_value = articles
        mock_llm.call_at = AsyncMock(return_value="LLM summary text")

        result = await generator.generate(date(2026, 7, 17), category="general")

        mock_storage.save_briefing.assert_awaited_once()
        save_kwargs = mock_storage.save_briefing.call_args.kwargs
        assert save_kwargs["briefing_date"] == date(2026, 7, 17)
        assert save_kwargs["category"] == "general"
        assert save_kwargs["summary"] == "LLM summary text"
        assert len(save_kwargs["items"]) == 2
        # Items preserve ranking by score descending
        assert save_kwargs["items"][0]["article_id"] == "art-1"
        assert save_kwargs["items"][0]["rank"] == 1
        assert save_kwargs["items"][1]["article_id"] == "art-2"
        assert save_kwargs["items"][1]["rank"] == 2
        # Result reflects persisted briefing
        assert result["id"] == 42
        assert result["briefing_date"] == date(2026, 7, 17)
        assert result["category"] == "general"
        assert result["summary"] == "LLM summary text"
        assert result["total_items"] == 2

    @pytest.mark.asyncio
    async def test_generate_caps_items_at_top_n(self, generator, mock_llm, mock_storage):
        """Briefing items are capped at TOP_N (10) to fit daily_briefing_items.rank CHECK constraint (1-10)."""
        articles = [
            _make_article(article_id=f"art-{i}", title=f"A{i}", score=0.9 - i * 0.01)
            for i in range(15)
        ]
        mock_storage.fetch_articles_for_briefing.return_value = articles
        mock_llm.call_at = AsyncMock(return_value="Summary")

        await generator.generate(date(2026, 7, 17), category="general")

        save_kwargs = mock_storage.save_briefing.call_args.kwargs
        assert len(save_kwargs["items"]) == 10
        # Ranks 1..10, no rank > 10 (CHECK constraint)
        ranks = [item["rank"] for item in save_kwargs["items"]]
        assert ranks == list(range(1, 11))


class TestBriefingGeneratorFailureModes:
    """Verify Rule 12 compliance — failures surface appropriately."""

    @pytest.mark.asyncio
    async def test_generate_no_articles_skips_llm_and_returns_empty(
        self, generator, mock_llm, mock_storage
    ):
        """No articles for the day → skip LLM call (save RPM budget) and return empty briefing."""
        mock_storage.fetch_articles_for_briefing.return_value = []

        result = await generator.generate(date(2026, 7, 17), category="general")

        mock_llm.call_at.assert_not_awaited()
        mock_storage.save_briefing.assert_not_awaited()
        assert result["id"] is None
        assert result["summary"] is None
        assert result["total_items"] == 0
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_generate_llm_failure_degrades_with_empty_summary(
        self, generator, mock_llm, mock_storage
    ):
        """LLM failure (AllProvidersFailedError) degrades: empty summary, briefing still persisted.

        Per spec R-briefing-002: 'LLM 调用失败时：summary 为空，log warning，不抛异常'.
        """
        mock_storage.fetch_articles_for_briefing.return_value = [_make_article(title="Article 1")]
        mock_llm.call_at = AsyncMock(side_effect=AllProvidersFailedError("rate limited"))

        result = await generator.generate(date(2026, 7, 17), category="general")

        # Briefing is still persisted with empty summary
        mock_storage.save_briefing.assert_awaited_once()
        save_kwargs = mock_storage.save_briefing.call_args.kwargs
        assert save_kwargs["summary"] is None
        assert result["summary"] is None

    @pytest.mark.asyncio
    async def test_generate_llm_circuit_open_degrades_with_empty_summary(
        self, generator, mock_llm, mock_storage
    ):
        """CircuitOpenError is also a degraded LLM failure (not a programming error)."""
        mock_storage.fetch_articles_for_briefing.return_value = [_make_article(title="Article 1")]
        mock_llm.call_at = AsyncMock(side_effect=CircuitOpenError("circuit open"))

        await generator.generate(date(2026, 7, 17), category="general")

        save_kwargs = mock_storage.save_briefing.call_args.kwargs
        assert save_kwargs["summary"] is None

    @pytest.mark.asyncio
    async def test_generate_llm_value_error_degrades_with_empty_summary(
        self, generator, mock_llm, mock_storage
    ):
        """ValueError (pydantic ValidationError / JSON parse) is a degraded LLM failure."""
        mock_storage.fetch_articles_for_briefing.return_value = [_make_article(title="Article 1")]
        mock_llm.call_at = AsyncMock(side_effect=ValueError("invalid JSON"))

        await generator.generate(date(2026, 7, 17), category="general")

        save_kwargs = mock_storage.save_briefing.call_args.kwargs
        assert save_kwargs["summary"] is None

    @pytest.mark.asyncio
    async def test_generate_storage_failure_propagates(self, generator, mock_llm, mock_storage):
        """Storage save_briefing failure must raise (Rule 12 — no silent drop).

        Caller (T010 scheduler / T009 endpoint) decides how to surface to user.
        """
        mock_storage.fetch_articles_for_briefing.return_value = [_make_article(title="Article 1")]
        mock_llm.call_at = AsyncMock(return_value="Summary")
        mock_storage.save_briefing.side_effect = Exception("DB connection lost")

        with pytest.raises(Exception, match="DB connection lost"):
            await generator.generate(date(2026, 7, 17), category="general")

    @pytest.mark.asyncio
    async def test_generate_unexpected_llm_error_propagates(
        self, generator, mock_llm, mock_storage
    ):
        """Non-LLM errors (TypeError, AttributeError) propagate — programming bugs must surface."""
        mock_storage.fetch_articles_for_briefing.return_value = [_make_article(title="Article 1")]
        mock_llm.call_at = AsyncMock(side_effect=TypeError("bad arg type"))

        with pytest.raises(TypeError, match="bad arg type"):
            await generator.generate(date(2026, 7, 17), category="general")


class TestBriefingGeneratorResultShape:
    """Verify BriefingGenerator return dict has fields required by T007 BriefingResult."""

    @pytest.mark.asyncio
    async def test_result_has_required_fields(self, generator, mock_llm, mock_storage):
        """Result dict has: id/briefing_date/category/summary/items/total_items/generated_at."""
        mock_storage.fetch_articles_for_briefing.return_value = [_make_article(title="Article 1")]
        mock_llm.call_at = AsyncMock(return_value="Summary")

        result = await generator.generate(date(2026, 7, 17), category="finance")

        required_keys = {
            "id",
            "briefing_date",
            "category",
            "summary",
            "items",
            "total_items",
            "generated_at",
        }
        assert required_keys.issubset(result.keys())
        assert isinstance(result["generated_at"], datetime)
