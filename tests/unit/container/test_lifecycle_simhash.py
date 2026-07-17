# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""T001 RED: lifecycle.py must wire simhash_dedup into DiscoveryProcessor.

Bug report (D1 dead code):
    src/container/lifecycle.py:1023-1028 instantiates DiscoveryProcessor
    without the ``simhash_dedup`` kwarg, leaving
    ``DiscoveryProcessor._simhash_dedup = None`` and disabling cross-source
    title deduplication. The fix is to add a ``simhash_dedup()`` factory in
    ``src/container/services.py`` and pass ``simhash_dedup=self.simhash_dedup()``
    in lifecycle.py:1023-1028.

This test exercises ``container.startup()`` with all heavy dependencies
stubbed, captures the ``DiscoveryProcessor`` instance via a patch, and
asserts ``_simhash_dedup is not None``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _stub_startup_dependencies(container) -> None:
    """Stub all heavy startup deps to isolate DiscoveryProcessor wiring."""
    container._shutdown = False
    container._settings = MagicMock()
    container._strategy = None  # skip PG init path
    container._live_config = None
    container._llm_client = None  # skip EmbeddingServiceWrapper / IntentClassifier
    container._llm_failure_repo = None
    container._llm_usage_buffer = None
    container._eval_compare_buffer = None

    from core.event import EventBus

    container._event_bus = EventBus()

    # Async init methods → no-op
    container.init_strategy = AsyncMock()
    container.init_cache_client = AsyncMock()
    container.init_llm = AsyncMock()
    container.init_search_engines = MagicMock()
    container._init_bm25_index = AsyncMock()
    container.init_smart_fetcher = AsyncMock()
    container.init_source_scheduler = AsyncMock()
    container.init_ml_components = AsyncMock()
    container.init_pipeline = AsyncMock()
    container.init_memory_service = AsyncMock()
    container.init_conflict_detector = AsyncMock()
    container.init_shift_detector = AsyncMock()
    container.init_briefing_engine = AsyncMock()
    container.init_causal_inference_service = AsyncMock()
    container._setup_scheduler = MagicMock()

    # Service factories used in DiscoveryProcessor instantiation
    container.crawler = MagicMock(return_value=MagicMock(name="crawler"))
    container.article_repo = MagicMock(return_value=MagicMock(name="article_repo"))
    container.deduplicator = MagicMock(return_value=MagicMock(name="deduplicator"))
    container.processing_queue = MagicMock(return_value=MagicMock(name="processing_queue"))

    # T002 will add simhash_dedup() factory to services.py.
    simhash_instance = MagicMock(name="simhash_dedup_instance")
    container.simhash_dedup = MagicMock(return_value=simhash_instance)

    # Worker / repos
    container.pipeline_worker = MagicMock(return_value=None)
    container.relational_pool = MagicMock(return_value=MagicMock())
    container.llm_usage_repo = MagicMock(return_value=MagicMock())
    container.pending_sync_repo = MagicMock(return_value=MagicMock())


@pytest.mark.asyncio
async def test_discovery_processor_receives_simhash_dedup() -> None:
    """Assert DiscoveryProcessor._simhash_dedup is not None after startup."""
    from src.container import Container

    container = Container()
    _stub_startup_dependencies(container)

    captured: dict[str, object] = {}

    class CapturingProcessor:
        def __init__(self, **kwargs):
            self._kwargs = kwargs
            self._simhash_dedup = kwargs.get("simhash_dedup")
            captured["instance"] = self

        async def on_items_discovered(self, *args, **kwargs):
            return None

    with patch("modules.ingestion.domain.processor.DiscoveryProcessor", CapturingProcessor):
        with patch("api.endpoints.deps_registry.Endpoints.initialize"):
            await container.startup()

    instance = captured.get("instance")
    assert instance is not None, "lifecycle.py must instantiate DiscoveryProcessor"
    assert instance._simhash_dedup is not None, (
        "DiscoveryProcessor._simhash_dedup must not be None after startup() — "
        "lifecycle.py:1023-1028 must pass simhash_dedup=self.simhash_dedup() (D1 dead code)"
    )
