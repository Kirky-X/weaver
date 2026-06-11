# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for CleanerNode trafilatura primary path with LLM fallback."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.ingestion.domain.models import RawArticle
from modules.processing.nodes.quality.cleaner import CleanerNode, _title_similarity
from modules.processing.pipeline.state import PipelineState

# ── Fixtures ──────────────────────────────────────────────────


def _make_raw(
    url: str = "https://example.com/article",
    title: str = "Test Article Title",
    body: str = "This is the article body with enough content.",
    html: str | None = None,
) -> RawArticle:
    return RawArticle(
        url=url,
        title=title,
        body=body,
        html=html,
        source="test",
        source_host="example.com",
        publish_time=datetime(2026, 1, 1),
    )


def _make_state(raw: RawArticle | None = None, **kwargs) -> PipelineState:
    if raw is None:
        raw = _make_raw()
    state: PipelineState = {"raw": raw}
    state.update(kwargs)
    return state


def _make_cleaner(**overrides) -> CleanerNode:
    defaults = {
        "llm": AsyncMock(),
        "budget": MagicMock(),
        "prompt_loader": MagicMock(),
        "min_body_chars": 100,
        "min_title_similarity": 0.7,
    }
    defaults.update(overrides)
    return CleanerNode(**defaults)


def _make_llm_output(
    title: str = "LLM Title",
    body: str = "LLM Body",
    tags: list[str] | None = None,
    entities: list | None = None,
) -> MagicMock:
    out = MagicMock()
    out.content.title = title
    out.content.subtitle = None
    out.content.summary = None
    out.content.body = body
    out.publish_time = None
    out.author = None
    out.tags = tags or []
    out.entities = entities or []
    return out


# ── _title_similarity tests ───────────────────────────────────


class TestTitleSimilarity:
    def test_identical_titles(self):
        assert _title_similarity("Hello World", "Hello World") == 1.0

    def test_empty_title(self):
        assert _title_similarity("", "Hello") == 0.0
        assert _title_similarity("Hello", "") == 0.0

    def test_similar_titles(self):
        sim = _title_similarity("Breaking News: Earthquake", "Breaking News: Flood")
        assert 0.5 < sim < 1.0

    def test_case_insensitive(self):
        sim = _title_similarity("hello world", "HELLO WORLD")
        assert sim == 1.0


# ── Trafilatura primary path tests ────────────────────────────


class TestCleanerTrafilaturaPrimary:
    """Test that trafilatura is tried first when HTML is available."""

    @pytest.mark.asyncio
    @patch("modules.processing.nodes.quality.cleaner.trafilatura")
    async def test_trafilatura_success_quality_ok_no_llm(self, mock_trafilatura):
        """(a) trafilatura succeeds + quality passes → no LLM call."""
        mock_trafilatura.extract.return_value = "A" * 200
        mock_trafilatura.bare_extraction.return_value = {
            "title": "Test Article Title",
            "author": "John Doe",
            "date": "2026-01-01",
        }

        llm = AsyncMock()
        cleaner = _make_cleaner(llm=llm)
        raw = _make_raw(html="<html><body><p>" + "A" * 200 + "</p></body></html>")
        state = _make_state(raw)

        result = await cleaner.execute(state)

        assert result["cleaner_method"] == "trafilatura"
        assert result["cleaned"]["body"] == "A" * 200
        assert result["cleaned"]["title"] == "Test Article Title"
        assert result["cleaned"]["author"] == "John Doe"
        assert result["tags"] == []
        assert result["cleaner_entities"] == []
        llm.call_at.assert_not_called()

    @pytest.mark.asyncio
    @patch("modules.processing.nodes.quality.cleaner.trafilatura")
    async def test_trafilatura_returns_none_fallback_llm(self, mock_trafilatura):
        """(b) trafilatura returns None → fallback to LLM."""
        mock_trafilatura.extract.return_value = None

        llm = AsyncMock()
        llm.call_at.return_value = _make_llm_output(title="Cleaned Title")

        budget = MagicMock()
        budget.truncate.return_value = "truncated body"

        cleaner = _make_cleaner(llm=llm, budget=budget)
        raw = _make_raw(html="<html>some html</html>")
        state = _make_state(raw)

        result = await cleaner.execute(state)

        assert result["cleaner_method"] == "llm"
        assert result["cleaned"]["title"] == "Cleaned Title"
        llm.call_at.assert_called_once()

    @pytest.mark.asyncio
    @patch("modules.processing.nodes.quality.cleaner.trafilatura")
    async def test_trafilatura_body_too_short_fallback_llm(self, mock_trafilatura):
        """(c) body < min_body_chars → fallback to LLM."""
        mock_trafilatura.extract.return_value = "Short"  # only 5 chars, < 100

        llm = AsyncMock()
        llm.call_at.return_value = _make_llm_output()

        budget = MagicMock()
        budget.truncate.return_value = "truncated"

        cleaner = _make_cleaner(llm=llm, budget=budget, min_body_chars=100)
        raw = _make_raw(html="<html>some html</html>")
        state = _make_state(raw)

        result = await cleaner.execute(state)

        assert result["cleaner_method"] == "llm"
        llm.call_at.assert_called_once()

    @pytest.mark.asyncio
    @patch("modules.processing.nodes.quality.cleaner.trafilatura")
    async def test_trafilatura_title_mismatch_fallback_llm(self, mock_trafilatura):
        """Title similarity below threshold → fallback to LLM."""
        mock_trafilatura.extract.return_value = "A" * 200
        mock_trafilatura.bare_extraction.return_value = {
            "title": "Completely Different Unrelated Title XYZ",
        }

        llm = AsyncMock()
        llm.call_at.return_value = _make_llm_output()

        budget = MagicMock()
        budget.truncate.return_value = "truncated"

        cleaner = _make_cleaner(llm=llm, budget=budget, min_title_similarity=0.7)
        raw = _make_raw(
            title="Test Article Title",
            html="<html>some html</html>",
        )
        state = _make_state(raw)

        result = await cleaner.execute(state)

        assert result["cleaner_method"] == "llm"
        llm.call_at.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_html_fallback_llm(self):
        """No HTML available → fallback to LLM without trafilatura attempt."""
        llm = AsyncMock()
        llm.call_at.return_value = _make_llm_output()

        budget = MagicMock()
        budget.truncate.return_value = "truncated"

        cleaner = _make_cleaner(llm=llm, budget=budget)
        raw = _make_raw(html=None)
        state = _make_state(raw)

        result = await cleaner.execute(state)

        assert result["cleaner_method"] == "llm"
        llm.call_at.assert_called_once()


# ── cleaner_method field tests ────────────────────────────────


class TestCleanerMethodField:
    """(d) cleaner_method field correctly set."""

    @pytest.mark.asyncio
    @patch("modules.processing.nodes.quality.cleaner.trafilatura")
    async def test_method_trafilatura(self, mock_trafilatura):
        mock_trafilatura.extract.return_value = "B" * 200
        mock_trafilatura.bare_extraction.return_value = {
            "title": "Test Article Title",
        }

        cleaner = _make_cleaner()
        raw = _make_raw(html="<html>html</html>")
        state = _make_state(raw)

        result = await cleaner.execute(state)

        assert result["cleaner_method"] == "trafilatura"

    @pytest.mark.asyncio
    async def test_method_llm(self):
        llm = AsyncMock()
        llm.call_at.return_value = _make_llm_output()

        budget = MagicMock()
        budget.truncate.return_value = "truncated"

        cleaner = _make_cleaner(llm=llm, budget=budget)
        raw = _make_raw(html=None)
        state = _make_state(raw)

        result = await cleaner.execute(state)

        assert result["cleaner_method"] == "llm"


# ── Prometheus metrics tests ──────────────────────────────────


class TestCleanerMetrics:
    """(e) Prometheus cleaner_method_total counter incremented."""

    @pytest.mark.asyncio
    @patch("modules.processing.nodes.quality.cleaner.trafilatura")
    @patch("modules.processing.nodes.quality.cleaner.metrics")
    async def test_trafilatura_metric_incremented(self, mock_metrics, mock_trafilatura):
        mock_trafilatura.extract.return_value = "C" * 200
        mock_trafilatura.bare_extraction.return_value = {
            "title": "Test Article Title",
        }
        mock_counter = MagicMock()
        mock_metrics.cleaner_method_total.labels.return_value = mock_counter

        cleaner = _make_cleaner()
        raw = _make_raw(html="<html>html</html>")
        state = _make_state(raw)

        await cleaner.execute(state)

        mock_metrics.cleaner_method_total.labels.assert_called_with(method="trafilatura")
        mock_counter.inc.assert_called_once()

    @pytest.mark.asyncio
    @patch("modules.processing.nodes.quality.cleaner.metrics")
    async def test_llm_metric_incremented(self, mock_metrics):
        llm = AsyncMock()
        llm.call_at.return_value = _make_llm_output()

        budget = MagicMock()
        budget.truncate.return_value = "truncated"

        mock_counter = MagicMock()
        mock_metrics.cleaner_method_total.labels.return_value = mock_counter

        cleaner = _make_cleaner(llm=llm, budget=budget)
        raw = _make_raw(html=None)
        state = _make_state(raw)

        await cleaner.execute(state)

        mock_metrics.cleaner_method_total.labels.assert_called_with(method="llm")
        mock_counter.inc.assert_called_once()


# ── Terminal state test ───────────────────────────────────────


class TestCleanerTerminalState:
    @pytest.mark.asyncio
    async def test_terminal_state_skips_cleaning(self):
        cleaner = _make_cleaner()
        raw = _make_raw()
        state = _make_state(raw, terminal=True)

        result = await cleaner.execute(state)

        assert "cleaned" not in result
        assert "cleaner_method" not in result
