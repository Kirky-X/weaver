# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""RED test for Pipeline Phase 3 concurrent nodes — P1-3 fix.

Phase 3 has 4 LLM-heavy nodes that are independent and can run
concurrently but currently execute serially:

- ``fake_news_detector`` (None-guarded)
- ``conflict_detector`` (always)
- ``narrative_generator`` (None-guarded)
- ``schema_extractor`` (None-guarded)

Serial cost: 4 × LLM latency. Concurrent: ~max latency.

This test asserts ``asyncio.gather`` concurrency: 4 nodes × 0.2s
delay each → total < 0.6s (serial would be ~0.8s).

See ``temp/report.md`` P1-3 (Phase3 并发) and specmark change
``fix-pipeline-deadcode-perf`` T023-T024.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_pipeline_with_mock_phase3_nodes() -> Any:
    """Create a Pipeline shell with 4 mock Phase 3 nodes + 0.2s delay each.

    Uses ``__new__`` to bypass the heavy ``Pipeline.__init__``. Only
    attributes touched by the Phase 3 concurrency block are set.
    """
    from modules.processing.pipeline.graph import Pipeline

    pipeline = Pipeline.__new__(Pipeline)
    pipeline._debug = False
    pipeline._phase3_semaphore = asyncio.Semaphore(5)

    # T004: empty disabled set — all independent stages execute
    pipeline._disabled_phase3_stage_names = set()

    node_delay = 0.2

    async def _slow_execute(state):
        await asyncio.sleep(node_delay)
        return state

    # 4 concurrent-able nodes
    pipeline._fake_news_node = MagicMock()
    pipeline._fake_news_node.execute = AsyncMock(side_effect=_slow_execute)

    pipeline._conflict_detector = MagicMock()
    pipeline._conflict_detector.execute = AsyncMock(side_effect=_slow_execute)

    pipeline._narrative_generator = MagicMock()
    pipeline._narrative_generator.execute = AsyncMock(side_effect=_slow_execute)

    pipeline._schema_extractor = MagicMock()
    pipeline._schema_extractor.execute = AsyncMock(side_effect=_slow_execute)

    # Serial nodes after the concurrent block — must be None/no-op to
    # isolate the concurrent-block timing.
    pipeline._sentiment_tracker = None
    pipeline._deps = MagicMock()
    pipeline._deps.nlp = MagicMock()
    pipeline._deps.nlp.entity_resolver = None

    # _update_processing_stage is called after each node; make it a no-op
    pipeline._update_processing_stage = AsyncMock()

    # Nodes before the concurrent block (re_vectorize / analyze / quality /
    # credibility / entity_extractor) — bypass by setting them to no-op
    # pass-through nodes that don't sleep.
    pipeline._re_vectorize = None  # skip via terminal flag
    pipeline._analyze = MagicMock()
    pipeline._analyze.execute = AsyncMock(side_effect=lambda s: s)
    pipeline._quality_scorer = MagicMock()
    pipeline._quality_scorer.execute = AsyncMock(side_effect=lambda s: s)
    pipeline._credibility = MagicMock()
    pipeline._credibility.execute = AsyncMock(side_effect=lambda s: s)
    pipeline._entity_extractor = MagicMock()
    pipeline._entity_extractor.execute = AsyncMock(side_effect=lambda s: s)

    return pipeline


@pytest.mark.asyncio
async def test_phase3_parallel_nodes_concurrent() -> None:
    """4 Phase 3 nodes (fake_news + conflict + narrative + schema) run concurrently.

    Each node sleeps 0.2s. Serial would be ~0.8s; concurrent ~0.2s.
    Assert total < 0.6s (3× single-node, allowing scheduling overhead).
    """
    pipeline = _make_pipeline_with_mock_phase3_nodes()

    # Construct minimal state: terminal=True to skip re_vectorize,
    # is_merged=False to enter Phase 3 body.
    state: dict[str, Any] = {"terminal": True, "is_merged": False}

    start = time.monotonic()
    await pipeline._phase3_per_article(state, pending_updates=[])
    elapsed = time.monotonic() - start

    # 4 nodes × 0.2s serial = 0.8s; concurrent ≈ 0.2s.
    # Ceiling 0.6s = 3× single node (generous for scheduling overhead).
    ceiling = 0.6
    assert elapsed < ceiling, (
        f"Expected concurrent Phase 3 nodes < {ceiling}s; got {elapsed:.2f}s "
        f"(serial would be ~0.8s for 4 × 0.2s nodes)"
    )
