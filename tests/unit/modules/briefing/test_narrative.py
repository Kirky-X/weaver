# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for NarrativeBriefingGenerator (T020 / R-briefing-007).

NarrativeBriefingGenerator produces narrative-style briefings by aggregating
NarrativeNode framing data (source_bias/frame/tone/emphasis) across multiple
articles for a given date + category.

Spec R-briefing-007 acceptance:
- Query NarrativeNode (HAS_NARRATIVE relationship from EventNode linked to
  Article via HAS_EVENT).
- Filter articles by category (delegated to storage.fetch_articles_for_briefing
  to reuse the existing category mapping decision — Rule 8 reuse).
- Call LLM aggregating multiple NarrativeNode framing dimensions.
- Raise InsufficientNarrativeError when NarrativeNode count < 3.

Failure handling (Rule 12 — fail loud):
- LLM failures degrade gracefully (empty summary, briefing still persisted),
  consistent with BriefingGenerator's R-briefing-002 contract.
- Storage failures raise to the caller.
- InsufficientNarrativeError is the explicit "no degradation" signal — caller
  (DailyBriefingService T021) catches it to fall back to template mode.
- Graph DB errors propagate (Rule 12).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from core.llm.resilience.circuit_breaker import CircuitOpenError
from core.llm.resilience.pool import AllProvidersFailedError
from core.llm.types import CallPoint
from modules.briefing.narrative import (
    InsufficientNarrativeError,
    NarrativeBriefingGenerator,
)


@pytest.fixture
def mock_graph_pool():
    """Mock GraphPool with execute_query AsyncMock."""
    pool = AsyncMock()
    pool.execute_query = AsyncMock(return_value=[])
    # database_type attribute absent by default → Neo4j branch
    return pool


@pytest.fixture
def mock_ladybug_pool():
    """Mock LadybugPool (database_type='ladybug')."""
    pool = AsyncMock()
    pool.execute_query = AsyncMock(return_value=[])
    pool.database_type = "ladybug"
    return pool


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    return AsyncMock()


@pytest.fixture
def mock_budget():
    """Mock token budget manager — truncate is a passthrough MagicMock."""
    budget = MagicMock()
    budget.truncate = MagicMock(side_effect=lambda text, call_point: text)
    return budget


@pytest.fixture
def mock_prompt_loader():
    """Mock prompt loader — returns canned templates."""
    loader = MagicMock()
    loader.get = MagicMock(return_value="Narrative briefing system prompt")
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
def generator(mock_graph_pool, mock_llm, mock_budget, mock_prompt_loader, mock_storage):
    """Create NarrativeBriefingGenerator with all mocks injected."""
    return NarrativeBriefingGenerator(
        graph_pool=mock_graph_pool,
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


def _make_narrative_row(
    *,
    article_id: str,
    source_bias: str = "中立",
    frame: str = "经济影响",
    tone: str = "客观",
    emphasis: str = "市场竞争",
) -> dict:
    """Build a NarrativeNode row as returned by graph_pool.execute_query."""
    return {
        "article_id": article_id,
        "source_bias": source_bias,
        "frame": frame,
        "tone": tone,
        "emphasis": emphasis,
    }


class TestInsufficientNarrativeError:
    """Verify InsufficientNarrativeError structure (R-briefing-007)."""

    def test_is_exception_subclass(self) -> None:
        """InsufficientNarrativeError must be an Exception (catchable by except)."""
        assert issubclass(InsufficientNarrativeError, Exception)

    def test_carries_narrative_count_and_threshold(self) -> None:
        """Error exposes narrative_count, threshold, briefing_date, category."""
        target_date = date(2026, 7, 17)
        err = InsufficientNarrativeError(
            narrative_count=2,
            threshold=3,
            briefing_date=target_date,
            category="finance",
            reason="insufficient NarrativeNode count",
        )
        assert err.narrative_count == 2
        assert err.threshold == 3
        assert err.briefing_date == target_date
        assert err.category == "finance"
        assert "insufficient" in str(err).lower() or "2" in str(err)


class TestNarrativeBriefingGeneratorCategoryFilter:
    """Verify NarrativeBriefingGenerator routes category to storage filter correctly."""

    @pytest.mark.asyncio
    async def test_generate_finance_passes_finance_to_storage(
        self, generator, mock_storage
    ) -> None:
        """finance category passed to storage.fetch_articles_for_briefing."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(article_id="a1", category="经济")
        ]
        # Provide 3 narratives (>= threshold) so generation proceeds.
        mock_graph_pool = generator._pool
        mock_graph_pool.execute_query = AsyncMock(
            return_value=[
                _make_narrative_row(article_id="a1"),
                _make_narrative_row(article_id="a1"),
                _make_narrative_row(article_id="a1"),
            ]
        )
        generator._llm.call_at = AsyncMock(return_value="Narrative summary")

        await generator.generate(date(2026, 7, 17), category="finance")

        call_kwargs = mock_storage.fetch_articles_for_briefing.call_args.kwargs
        assert call_kwargs["briefing_date"] == date(2026, 7, 17)
        assert call_kwargs["category"] == "finance"

    @pytest.mark.asyncio
    async def test_generate_none_category_normalized_to_general(
        self, generator, mock_storage
    ) -> None:
        """None category is normalized to 'general' before calling storage."""
        mock_storage.fetch_articles_for_briefing.return_value = [_make_article(article_id="a1")]
        generator._pool.execute_query = AsyncMock(
            return_value=[
                _make_narrative_row(article_id="a1"),
                _make_narrative_row(article_id="a1"),
                _make_narrative_row(article_id="a1"),
            ]
        )
        generator._llm.call_at = AsyncMock(return_value="Summary")

        await generator.generate(date(2026, 7, 17), category=None)

        call_kwargs = mock_storage.fetch_articles_for_briefing.call_args.kwargs
        assert call_kwargs["category"] == "general"

    @pytest.mark.asyncio
    async def test_generate_invalid_category_raises_value_error(self, generator) -> None:
        """Invalid category must raise ValueError (Rule 12 — fail loud)."""
        with pytest.raises(ValueError, match="Invalid category"):
            await generator.generate(date(2026, 7, 17), category="sports")


class TestNarrativeBriefingGeneratorNarrativeQuery:
    """Verify NarrativeNode query via graph DB (R-briefing-007)."""

    @pytest.mark.asyncio
    async def test_generate_queries_narrative_node_for_articles(
        self, generator, mock_storage, mock_graph_pool
    ) -> None:
        """generate() queries NarrativeNode via graph_pool.execute_query."""
        articles = [
            _make_article(article_id="art-1"),
            _make_article(article_id="art-2"),
        ]
        mock_storage.fetch_articles_for_briefing.return_value = articles
        # Provide 3 narratives for each article (6 total).
        mock_graph_pool.execute_query = AsyncMock(
            return_value=[
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-2"),
                _make_narrative_row(article_id="art-2"),
            ]
        )
        generator._llm.call_at = AsyncMock(return_value="Narrative summary")

        await generator.generate(date(2026, 7, 17), category="general")

        mock_graph_pool.execute_query.assert_awaited()
        # The query must reference NarrativeNode and HAS_NARRATIVE.
        call_args = mock_graph_pool.execute_query.call_args
        query_text = call_args.args[0] if call_args.args else call_args.kwargs.get("query", "")
        assert "NarrativeNode" in query_text
        assert "HAS_NARRATIVE" in query_text

    @pytest.mark.asyncio
    async def test_generate_ladybug_pool_uses_int64_timestamp_params(
        self, mock_ladybug_pool, mock_llm, mock_budget, mock_prompt_loader, mock_storage
    ) -> None:
        """LadybugDB pool triggers INT64 timestamp branch (temporal.py pattern)."""
        articles = [_make_article(article_id="art-1")]
        mock_storage.fetch_articles_for_briefing.return_value = articles
        mock_ladybug_pool.execute_query = AsyncMock(
            return_value=[
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
            ]
        )
        mock_llm.call_at = AsyncMock(return_value="Summary")

        gen = NarrativeBriefingGenerator(
            graph_pool=mock_ladybug_pool,
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            storage=mock_storage,
        )
        await gen.generate(date(2026, 7, 17), category="general")

        # Ladybug branch should be detected — verify query was issued.
        mock_ladybug_pool.execute_query.assert_awaited()


class TestNarrativeBriefingGeneratorThreshold:
    """Verify InsufficientNarrativeError raised when NarrativeNode count < 3."""

    @pytest.mark.asyncio
    async def test_generate_raises_insufficient_when_zero_narratives(
        self, generator, mock_storage, mock_graph_pool
    ) -> None:
        """0 NarrativeNodes → InsufficientNarrativeError."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(article_id="art-1"),
        ]
        mock_graph_pool.execute_query = AsyncMock(return_value=[])

        with pytest.raises(InsufficientNarrativeError) as exc_info:
            await generator.generate(date(2026, 7, 17), category="general")

        assert exc_info.value.narrative_count == 0
        assert exc_info.value.threshold == 3
        assert exc_info.value.briefing_date == date(2026, 7, 17)
        assert exc_info.value.category == "general"

    @pytest.mark.asyncio
    async def test_generate_raises_insufficient_when_two_narratives(
        self, generator, mock_storage, mock_graph_pool
    ) -> None:
        """2 NarrativeNodes (< threshold 3) → InsufficientNarrativeError."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(article_id="art-1"),
            _make_article(article_id="art-2"),
        ]
        mock_graph_pool.execute_query = AsyncMock(
            return_value=[
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-2"),
            ]
        )

        with pytest.raises(InsufficientNarrativeError) as exc_info:
            await generator.generate(date(2026, 7, 17), category="general")

        assert exc_info.value.narrative_count == 2
        assert exc_info.value.threshold == 3

    @pytest.mark.asyncio
    async def test_generate_raises_insufficient_when_no_articles(
        self, generator, mock_storage
    ) -> None:
        """No articles → InsufficientNarrativeError (narrative_count=0)."""
        mock_storage.fetch_articles_for_briefing.return_value = []

        with pytest.raises(InsufficientNarrativeError) as exc_info:
            await generator.generate(date(2026, 7, 17), category="general")

        assert exc_info.value.narrative_count == 0

    @pytest.mark.asyncio
    async def test_generate_proceeds_with_three_narratives(
        self, generator, mock_storage, mock_graph_pool, mock_llm
    ) -> None:
        """3 NarrativeNodes (== threshold) → proceeds, no InsufficientNarrativeError."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(article_id="art-1"),
            _make_article(article_id="art-2"),
        ]
        mock_graph_pool.execute_query = AsyncMock(
            return_value=[
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-2"),
            ]
        )
        mock_llm.call_at = AsyncMock(return_value="Narrative summary")

        result = await generator.generate(date(2026, 7, 17), category="general")

        assert result["summary"] == "Narrative summary"
        assert result["total_items"] == 2


class TestNarrativeBriefingGeneratorLLMCall:
    """Verify NarrativeBriefingGenerator calls LLM with narrative framing data."""

    @pytest.mark.asyncio
    async def test_generate_calls_llm_with_briefing_call_point(
        self, generator, mock_storage, mock_graph_pool, mock_llm
    ) -> None:
        """LLM call uses CallPoint.BRIEFING (same as BriefingGenerator)."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(article_id="art-1"),
        ]
        mock_graph_pool.execute_query = AsyncMock(
            return_value=[
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
            ]
        )
        mock_llm.call_at = AsyncMock(return_value="Narrative summary")

        await generator.generate(date(2026, 7, 17), category="general")

        mock_llm.call_at.assert_awaited_once()
        call_args = mock_llm.call_at.call_args
        assert call_args.args[0] == CallPoint.BRIEFING

    @pytest.mark.asyncio
    async def test_generate_includes_narrative_framing_in_llm_payload(
        self, generator, mock_storage, mock_graph_pool, mock_llm
    ) -> None:
        """LLM payload includes source_bias/frame/tone/emphasis from NarrativeNodes.

        BriefingGenerator passes payload as the 2nd positional arg to call_at
        (convention — Rule 11). The payload includes ``narrative_framing``
        key mapping article_id → list of framing dicts.
        """
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(article_id="art-1", title="Article 1"),
        ]
        mock_graph_pool.execute_query = AsyncMock(
            return_value=[
                _make_narrative_row(
                    article_id="art-1",
                    source_bias="左倾",
                    frame="政策监管",
                    tone="批判",
                    emphasis="风险警示",
                ),
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
            ]
        )
        mock_llm.call_at = AsyncMock(return_value="Narrative summary")

        await generator.generate(date(2026, 7, 17), category="general")

        # call_at(CallPoint.BRIEFING, payload) — payload is 2nd positional arg.
        call_args = mock_llm.call_at.call_args
        payload = (
            call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("payload", {})
        )
        assert isinstance(payload, dict)
        # Payload must include narrative_framing key with per-article framing list.
        assert "narrative_framing" in payload
        framing = payload["narrative_framing"]
        assert "art-1" in framing
        article_framings = framing["art-1"]
        assert len(article_framings) == 3
        # First framing has the special values.
        first = article_framings[0]
        assert first["source_bias"] == "左倾"
        assert first["frame"] == "政策监管"
        assert first["tone"] == "批判"
        assert first["emphasis"] == "风险警示"


class TestNarrativeBriefingGeneratorPersistence:
    """Verify NarrativeBriefingGenerator persists via storage.save_briefing."""

    @pytest.mark.asyncio
    async def test_generate_persists_briefing_with_summary(
        self, generator, mock_storage, mock_graph_pool, mock_llm
    ) -> None:
        """Successful generation persists briefing with LLM-generated summary."""
        articles = [
            _make_article(article_id="art-1", title="A1", score=0.9),
            _make_article(article_id="art-2", title="A2", score=0.8),
        ]
        mock_storage.fetch_articles_for_briefing.return_value = articles
        mock_graph_pool.execute_query = AsyncMock(
            return_value=[
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-2"),
                _make_narrative_row(article_id="art-1"),
            ]
        )
        mock_llm.call_at = AsyncMock(return_value="LLM narrative summary")

        result = await generator.generate(date(2026, 7, 17), category="general")

        mock_storage.save_briefing.assert_awaited_once()
        save_kwargs = mock_storage.save_briefing.call_args.kwargs
        assert save_kwargs["briefing_date"] == date(2026, 7, 17)
        assert save_kwargs["category"] == "general"
        assert save_kwargs["summary"] == "LLM narrative summary"
        assert len(save_kwargs["items"]) == 2
        # Items preserve ranking by score descending
        assert save_kwargs["items"][0]["article_id"] == "art-1"
        assert save_kwargs["items"][0]["rank"] == 1
        # Result reflects persisted briefing
        assert result["id"] == 42
        assert result["briefing_date"] == date(2026, 7, 17)
        assert result["category"] == "general"
        assert result["summary"] == "LLM narrative summary"

    @pytest.mark.asyncio
    async def test_generate_caps_items_at_top_n(
        self, generator, mock_storage, mock_graph_pool, mock_llm
    ) -> None:
        """Briefing items capped at TOP_N (10) per daily_briefing_items.rank CHECK."""
        articles = [
            _make_article(article_id=f"art-{i}", title=f"A{i}", score=0.9 - i * 0.01)
            for i in range(15)
        ]
        mock_storage.fetch_articles_for_briefing.return_value = articles
        mock_graph_pool.execute_query = AsyncMock(
            return_value=[
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-2"),
                _make_narrative_row(article_id="art-3"),
            ]
        )
        mock_llm.call_at = AsyncMock(return_value="Summary")

        await generator.generate(date(2026, 7, 17), category="general")

        save_kwargs = mock_storage.save_briefing.call_args.kwargs
        assert len(save_kwargs["items"]) == 10
        ranks = [item["rank"] for item in save_kwargs["items"]]
        assert ranks == list(range(1, 11))


class TestNarrativeBriefingGeneratorFailureModes:
    """Verify Rule 12 compliance — failures surface appropriately."""

    @pytest.mark.asyncio
    async def test_generate_llm_failure_degrades_to_empty_summary(
        self, generator, mock_storage, mock_graph_pool, mock_llm
    ) -> None:
        """LLM failure → summary=None, briefing still persisted (R-briefing-002)."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(article_id="art-1"),
        ]
        mock_graph_pool.execute_query = AsyncMock(
            return_value=[
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
            ]
        )
        mock_llm.call_at = AsyncMock(
            side_effect=AllProvidersFailedError("All LLM providers failed")
        )

        result = await generator.generate(date(2026, 7, 17), category="general")

        assert result["summary"] is None
        mock_storage.save_briefing.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_circuit_open_degrades_to_empty_summary(
        self, generator, mock_storage, mock_graph_pool, mock_llm
    ) -> None:
        """CircuitOpenError → degraded summary=None, briefing still persisted."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(article_id="art-1"),
        ]
        mock_graph_pool.execute_query = AsyncMock(
            return_value=[
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
            ]
        )
        mock_llm.call_at = AsyncMock(side_effect=CircuitOpenError("circuit open"))

        result = await generator.generate(date(2026, 7, 17), category="general")

        assert result["summary"] is None

    @pytest.mark.asyncio
    async def test_generate_value_error_degrades_to_empty_summary(
        self, generator, mock_storage, mock_graph_pool, mock_llm
    ) -> None:
        """ValueError (pydantic ValidationError) → degraded summary=None."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(article_id="art-1"),
        ]
        mock_graph_pool.execute_query = AsyncMock(
            return_value=[
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
            ]
        )
        mock_llm.call_at = AsyncMock(side_effect=ValueError("invalid LLM output"))

        result = await generator.generate(date(2026, 7, 17), category="general")

        assert result["summary"] is None

    @pytest.mark.asyncio
    async def test_generate_graph_db_error_propagates(
        self, generator, mock_storage, mock_graph_pool
    ) -> None:
        """Graph DB error propagates to caller (Rule 12 — fail loud)."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(article_id="art-1"),
        ]
        mock_graph_pool.execute_query = AsyncMock(
            side_effect=RuntimeError("graph DB connection lost")
        )

        with pytest.raises(RuntimeError, match="graph DB connection lost"):
            await generator.generate(date(2026, 7, 17), category="general")

    @pytest.mark.asyncio
    async def test_generate_storage_failure_propagates(
        self, generator, mock_storage, mock_graph_pool, mock_llm
    ) -> None:
        """Storage save_briefing failure propagates (Rule 12)."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(article_id="art-1"),
        ]
        mock_graph_pool.execute_query = AsyncMock(
            return_value=[
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
            ]
        )
        mock_llm.call_at = AsyncMock(return_value="Summary")
        mock_storage.save_briefing = AsyncMock(side_effect=RuntimeError("DB write failed"))

        with pytest.raises(RuntimeError, match="DB write failed"):
            await generator.generate(date(2026, 7, 17), category="general")

    @pytest.mark.asyncio
    async def test_generate_unexpected_llm_error_propagates(
        self, generator, mock_storage, mock_graph_pool, mock_llm
    ) -> None:
        """Unexpected Exception (TypeError/AttributeError) propagates (Rule 12)."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(article_id="art-1"),
        ]
        mock_graph_pool.execute_query = AsyncMock(
            return_value=[
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
            ]
        )
        mock_llm.call_at = AsyncMock(side_effect=TypeError("unexpected programming bug"))

        with pytest.raises(TypeError, match="unexpected programming bug"):
            await generator.generate(date(2026, 7, 17), category="general")


class TestNarrativeBriefingGeneratorReturnShape:
    """Verify return dict shape matches BriefingGenerator (R-briefing-002 contract)."""

    @pytest.mark.asyncio
    async def test_generate_returns_dict_with_required_fields(
        self, generator, mock_storage, mock_graph_pool, mock_llm
    ) -> None:
        """Return dict has id/briefing_date/category/summary/items/total_items/generated_at."""
        mock_storage.fetch_articles_for_briefing.return_value = [
            _make_article(article_id="art-1", title="A1", score=0.9),
        ]
        mock_graph_pool.execute_query = AsyncMock(
            return_value=[
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
                _make_narrative_row(article_id="art-1"),
            ]
        )
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
        assert result["category"] == "finance"
        assert result["total_items"] == 1
        assert isinstance(result["items"], list)
        assert isinstance(result["generated_at"], datetime)
