# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""RED test for Pipeline Phase 3 independent stage skipping — D1 config-driven.

Phase 3 has 5 independent stages (no downstream dependencies) that should
respect the TOML `enabled=false` flag:

- ``fake_news_detector`` (None-guarded)
- ``conflict_detector`` (always)
- ``narrative_schema`` (None-guarded)
- ``sentiment_tracker`` (None-guarded)

Dependency stages (``re_vectorize``/``analyze``/``quality_scorer``/
``credibility``/``entity_extractor``) must ALWAYS execute regardless of
TOML ``enabled`` to avoid breaking downstream stages.

Design choice: Pipeline tracks ``_disabled_phase3_stage_names`` (explicit
disable set) rather than enabled set. This preserves backward compatibility
when TOML does not configure stages (empty list → nothing disabled).

This test asserts:
1. Independent stage with disabled flag is SKIPPED (node.execute not called)
2. Independent stage without disabled flag is EXECUTED
3. Dependency stage executes even when TOML says enabled=false
4. Multiple independent stages can be disabled simultaneously

See specmark/changes/fix-deadcode-integration T004-T005.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_pipeline_with_mock_nodes(
    disabled_stage_names: set[str] | None = None,
) -> Any:
    """Create a Pipeline shell with mock Phase 3 nodes.

    Uses ``__new__`` to bypass the heavy ``Pipeline.__init__``. Sets
    ``_disabled_phase3_stage_names`` to control which independent stages
    should be skipped.

    Args:
        disabled_stage_names: Set of disabled stage names. If None, empty
            set (all independent stages execute — backward-compatible default).
    """
    from modules.processing.pipeline.graph import Pipeline

    pipeline = Pipeline.__new__(Pipeline)
    pipeline._debug = False
    pipeline._phase3_semaphore = asyncio.Semaphore(5)

    # T004: set of explicitly-disabled independent stage names
    pipeline._disabled_phase3_stage_names = disabled_stage_names or set()

    # 4 concurrent-able independent nodes
    pipeline._fake_news_node = MagicMock()
    pipeline._fake_news_node.execute = AsyncMock(return_value=None)

    pipeline._conflict_detector = MagicMock()
    pipeline._conflict_detector.execute = AsyncMock(return_value=None)

    pipeline._narrative_schema = MagicMock()
    pipeline._narrative_schema.execute = AsyncMock(return_value=None)

    # sentiment_tracker (serial after concurrent block)
    pipeline._sentiment_tracker = MagicMock()
    pipeline._sentiment_tracker.execute = AsyncMock(side_effect=lambda s: s)

    # _update_processing_stage is called after each node; make it a no-op
    pipeline._update_processing_stage = AsyncMock()

    # Dependency nodes (must always execute regardless of enabled flag)
    pipeline._re_vectorize = MagicMock()
    pipeline._re_vectorize.execute = AsyncMock(side_effect=lambda s: s)
    pipeline._analyze = MagicMock()
    pipeline._analyze.execute = AsyncMock(side_effect=lambda s: s)
    pipeline._quality_scorer = MagicMock()
    pipeline._quality_scorer.execute = AsyncMock(side_effect=lambda s: s)
    pipeline._credibility = MagicMock()
    pipeline._credibility.execute = AsyncMock(side_effect=lambda s: s)
    pipeline._entity_extractor = MagicMock()
    pipeline._entity_extractor.execute = AsyncMock(side_effect=lambda s: s)

    # entity_resolver (after sentiment_tracker) — disabled to isolate
    pipeline._deps = MagicMock()
    pipeline._deps.nlp = MagicMock()
    pipeline._deps.nlp.entity_resolver = None

    return pipeline


@pytest.mark.asyncio
async def test_independent_stage_skipped_when_disabled() -> None:
    """fake_news_detector with disabled flag is SKIPPED.

    Constructs pipeline with _disabled_phase3_stage_names containing
    'fake_news_detector', calls _phase3_per_article, asserts
    _fake_news_node.execute was NOT called.
    """
    pipeline = _make_pipeline_with_mock_nodes(disabled_stage_names={"fake_news_detector"})

    state: dict[str, Any] = {
        "terminal": False,
        "is_merged": False,
        "raw": MagicMock(url="http://test"),
    }
    await pipeline._phase3_per_article(state, pending_updates=[])

    pipeline._fake_news_node.execute.assert_not_called()
    # Other independent stages still execute
    pipeline._conflict_detector.execute.assert_called_once()
    pipeline._narrative_schema.execute.assert_called_once()


@pytest.mark.asyncio
async def test_independent_stage_executed_when_not_disabled() -> None:
    """fake_news_detector without disabled flag is EXECUTED.

    Default _disabled_phase3_stage_names is empty (backward-compatible).
    """
    pipeline = _make_pipeline_with_mock_nodes()  # empty disabled set

    state: dict[str, Any] = {
        "terminal": False,
        "is_merged": False,
        "raw": MagicMock(url="http://test"),
    }
    await pipeline._phase3_per_article(state, pending_updates=[])

    pipeline._fake_news_node.execute.assert_called_once()
    pipeline._conflict_detector.execute.assert_called_once()
    pipeline._narrative_schema.execute.assert_called_once()
    pipeline._sentiment_tracker.execute.assert_called_once()


@pytest.mark.asyncio
async def test_dependency_stage_executed_even_if_disabled_in_toml() -> None:
    """entity_extractor (dependency stage) executes even when TOML says enabled=false.

    _disabled_phase3_stage_names contains 'entity_extractor', but
    entity_extractor must still execute because sentiment_tracker and
    entity_resolver depend on its output. Only independent stages respect
    the disabled flag.
    """
    pipeline = _make_pipeline_with_mock_nodes(
        disabled_stage_names={
            "fake_news_detector",
            "conflict_detector",
            "narrative_schema",
            "sentiment_tracker",
            "entity_extractor",  # dependency stage — should be ignored
            "re_vectorize",  # dependency stage — should be ignored
            "analyze",  # dependency stage — should be ignored
        }
    )

    state: dict[str, Any] = {
        "terminal": False,
        "is_merged": False,
        "raw": MagicMock(url="http://test"),
    }
    await pipeline._phase3_per_article(state, pending_updates=[])

    # Dependency stages execute regardless of disabled flag
    pipeline._entity_extractor.execute.assert_called_once()
    pipeline._re_vectorize.execute.assert_called_once()
    pipeline._analyze.execute.assert_called_once()
    pipeline._quality_scorer.execute.assert_called_once()
    pipeline._credibility.execute.assert_called_once()
    # All 5 independent stages skipped
    pipeline._fake_news_node.execute.assert_not_called()
    pipeline._conflict_detector.execute.assert_not_called()
    pipeline._narrative_schema.execute.assert_not_called()
    pipeline._sentiment_tracker.execute.assert_not_called()


@pytest.mark.asyncio
async def test_multiple_independent_stages_skipped() -> None:
    """Multiple independent stages can be disabled simultaneously.

    Disable fake_news_detector + narrative_generator + schema_extractor +
    sentiment_tracker; only conflict_detector remains enabled.
    """
    pipeline = _make_pipeline_with_mock_nodes(
        disabled_stage_names={
            "fake_news_detector",
            "narrative_schema",
            "sentiment_tracker",
        }
    )

    state: dict[str, Any] = {
        "terminal": False,
        "is_merged": False,
        "raw": MagicMock(url="http://test"),
    }
    await pipeline._phase3_per_article(state, pending_updates=[])

    # Only conflict_detector executes among independent stages
    pipeline._conflict_detector.execute.assert_called_once()
    pipeline._fake_news_node.execute.assert_not_called()
    pipeline._narrative_schema.execute.assert_not_called()
    pipeline._sentiment_tracker.execute.assert_not_called()


# ── T006: TOML ↔ graph.py mapping consistency ─────────────────────────


def test_toml_phase3_stage_names_subset_of_graph_phase3_stages() -> None:
    """Every TOML phase3 stage name must exist in PHASE3_STAGES.

    If TOML declares a stage name that graph.py doesn't recognize, the
    enabled=false flag would be silently ignored (no-op). This test
    catches drift between TOML config and graph.py implementation.
    """
    from modules.processing.pipeline.config import PipelineSettings
    from modules.processing.pipeline.graph import PHASE3_STAGES

    settings = PipelineSettings()
    toml_stage_names = {s.name for s in settings.phase3.stages if s.name}

    unknown = toml_stage_names - set(PHASE3_STAGES.keys())
    assert not unknown, (
        f"TOML phase3.stages declares names not in PHASE3_STAGES: {unknown}. "
        f"Either add them to graph.py PHASE3_STAGES or remove from TOML."
    )


def test_independent_stage_names_all_in_graph_phase3_stages() -> None:
    """All 4 independent stage names must be in PHASE3_STAGES.

    Independent stages are the ones graph.py checks against
    _disabled_phase3_stage_names. If any name is missing from
    PHASE3_STAGES, the _update_processing_stage call after the node
    would KeyError.
    """
    from modules.processing.pipeline.graph import PHASE3_STAGES

    independent_stages = {
        "fake_news_detector",
        "conflict_detector",
        "narrative_schema",
        "sentiment_tracker",
    }

    missing = independent_stages - set(PHASE3_STAGES.keys())
    assert not missing, (
        f"Independent stage names missing from PHASE3_STAGES: {missing}. "
        f"graph.py _phase3_per_article would KeyError on stage update."
    )
