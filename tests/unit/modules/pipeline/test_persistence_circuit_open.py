# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""T016: circuit-open graph writes are recorded into pending_sync."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.graph.neo4j_writer import Neo4jWriteCircuitOpen
from modules.processing.pipeline.persistence import PipelinePersistence


@pytest.fixture
def persistence_deps():
    article_repo = MagicMock()
    article_repo.mark_failed = AsyncMock()
    pending_sync_repo = MagicMock()
    pending_sync_repo.upsert = AsyncMock(return_value=1)
    persistence = PipelinePersistence(
        article_repo=article_repo,
        vector_repo=None,
        graph_writer=MagicMock(),
        phase3_concurrency=2,
        pending_sync_repo=pending_sync_repo,
    )
    return persistence, article_repo, pending_sync_repo


@pytest.mark.asyncio
async def test_circuit_open_records_pending_sync(persistence_deps):
    persistence, article_repo, pending_sync_repo = persistence_deps
    state = {
        "article_id": str(uuid.uuid4()),
        "raw": MagicMock(url="https://example.com/a"),
    }

    completed, failed = await persistence._handle_graph_persist_failure(
        state, Neo4jWriteCircuitOpen("open"), batch_total=1, batch_completed=0, batch_failed=0
    )

    pending_sync_repo.upsert.assert_awaited_once()
    args, kwargs = pending_sync_repo.upsert.await_args
    assert str(args[0]) == state["article_id"]
    assert failed == 1 and completed == 0


@pytest.mark.asyncio
async def test_other_failures_do_not_touch_pending_sync(persistence_deps):
    persistence, article_repo, pending_sync_repo = persistence_deps
    state = {
        "article_id": str(uuid.uuid4()),
        "raw": MagicMock(url="https://example.com/b"),
    }

    await persistence._handle_graph_persist_failure(
        state, RuntimeError("generic graph error"), 1, 0, 0
    )

    pending_sync_repo.upsert.assert_not_awaited()
    article_repo.mark_failed.assert_awaited_once()


@pytest.mark.asyncio
async def test_circuit_open_without_repo_still_marks_failed(persistence_deps):
    persistence, article_repo, pending_sync_repo = persistence_deps
    persistence._pending_sync_repo = None
    state = {
        "article_id": str(uuid.uuid4()),
        "raw": MagicMock(url="https://example.com/c"),
    }

    completed, failed = await persistence._handle_graph_persist_failure(
        state, Neo4jWriteCircuitOpen("open"), 1, 0, 0
    )

    pending_sync_repo.upsert.assert_not_awaited()
    article_repo.mark_failed.assert_awaited_once()
    assert failed == 1
