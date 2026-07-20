# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""End-to-end integration tests for briefings narrative_mode (T022 / R-briefing-008).

Verifies the T022 factory integration: _get_briefing_service() correctly
constructs DailyBriefingService with NarrativeBriefingGenerator injected
when container.graph_pool() is available, and returns narrative_generator=None
when graph_pool is unavailable (degraded mode).

These tests use REAL fixtures from tests/integration/conftest.py:
- relational_pool: PostgreSQL → DuckDB auto-fallback (real DB)
- graph_pool: Neo4j → LadybugDB auto-fallback (real DB)
- prompt_loader: real PromptLoader from config/prompts

LLM is replaced with a stub class (FakeLLMClient) shared from
.conftest — NOT unittest.mock.MagicMock. Project hook forbids MagicMock
in integration tests (Rule: integration tests MUST use real services).
The stub is a real Python class implementing the LLMClient interface;
_get_briefing_service only needs container.llm_client() to return an
object with .call_at() method — it does NOT call .call_at() during
factory construction, so the stub never actually returns LLM responses.
This avoids real Ollama calls + RPM consumption.

Tests do NOT call generate_briefing() — that would require:
1. Real LLM API calls (RPM consumption, 429 risk)
2. Seeded articles + NarrativeNode data (>= 3 for non-degrade path)

The 3 narrative_mode scenarios (success / degrade / template) are fully
covered by unit tests:
- T021 tests/unit/modules/briefing/test_service_narrative_mode.py (14 tests)
- T022 tests/unit/api/endpoints/test_briefings.py (21 tests, HTTP layer)

This file verifies the container integration seam: factory wiring is correct.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from container import Container, set_container
from core.db.strategy import DatabaseStrategy
from modules.briefing import DailyBriefingService
from modules.briefing.narrative import NarrativeBriefingGenerator

from .conftest import FakeLLMClient, FakePromptLoader


def _build_container(
    relational_pool_fixture,
    graph_pool_fixture,
) -> Container:
    """Build a real Container with real pools + stub LLM/prompt_loader.

    Uses real relational_pool + graph_pool fixtures (DuckDB/LadybugDB
    fallback). LLM is FakeLLMClient (stub) — factory only wires it as
    dependency, never invokes during construction.
    """
    rel_pool, rel_type = relational_pool_fixture
    container = Container()
    container._strategy = DatabaseStrategy(
        relational_pool=rel_pool,
        graph_pool=graph_pool_fixture[0] if graph_pool_fixture else None,
        relational_type=rel_type,
        graph_type=graph_pool_fixture[1] if graph_pool_fixture else None,
    )
    container._llm_client = FakeLLMClient()
    container._prompt_loader = FakePromptLoader()
    return container


class TestGetBriefingServiceContainerIntegration:
    """Verify _get_briefing_service() factory integrates with container correctly.

    These tests verify the T022 wiring: factory constructs the correct
    DailyBriefingService shape (with/without narrative_generator) based
    on container.graph_pool() availability.
    """

    @pytest.fixture(autouse=True)
    def reset_container(self):
        """Reset global container before and after each test."""
        set_container(None)
        yield
        set_container(None)

    @pytest.mark.asyncio
    async def test_get_briefing_service_injects_narrative_generator_when_graph_available(
        self,
        relational_pool,
        graph_pool,
    ):
        """When graph_pool is available, factory injects NarrativeBriefingGenerator.

        Verifies T022 container integration: _get_briefing_service() constructs
        NarrativeBriefingGenerator from graph_pool + llm + budget + prompt_loader
        + storage, and passes it as narrative_generator to DailyBriefingService.
        """
        container = _build_container(relational_pool, graph_pool)
        set_container(container)

        # Lazy import (mirrors endpoint pattern).
        from api.endpoints.briefings import _get_briefing_service

        service = _get_briefing_service()

        # Verify service is DailyBriefingService.
        assert isinstance(service, DailyBriefingService)
        # Verify narrative_generator is injected (not None).
        assert service._narrative_generator is not None
        # Verify narrative_generator is NarrativeBriefingGenerator instance.
        assert isinstance(service._narrative_generator, NarrativeBriefingGenerator)
        # Verify template generator is also present.
        assert service._generator is not None

    @pytest.mark.asyncio
    async def test_get_briefing_service_returns_none_narrative_when_graph_unavailable(
        self,
        relational_pool,
    ):
        """When graph_pool is None, factory returns narrative_generator=None.

        Verifies degraded mode: factory still constructs BriefingGenerator +
        DailyBriefingService (template mode works), but narrative_generator
        is None — narrative_mode=True will raise ValueError (Rule 12 fail-loud)
        which the HTTP handler maps to 503.
        """
        container = _build_container(relational_pool, None)
        set_container(container)

        from api.endpoints.briefings import _get_briefing_service

        service = _get_briefing_service()

        assert isinstance(service, DailyBriefingService)
        # narrative_generator is None (degraded mode).
        assert service._narrative_generator is None
        # But template generator is still available (template mode works).
        assert service._generator is not None

    @pytest.mark.asyncio
    async def test_get_briefing_service_raises_503_when_relational_pool_none(self):
        """When relational_pool is None, factory raises HTTPException 503.

        Verifies R-briefing-008 fail-loud: relational pool is required for
        both template and narrative mode (storage layer dependency). Without
        it, the service cannot be constructed — fail with 503 (not 500).
        """
        container = Container()
        # Strategy with both pools None.
        container._strategy = DatabaseStrategy(
            relational_pool=None,
            graph_pool=None,
            relational_type=None,
            graph_type=None,
        )
        container._llm_client = FakeLLMClient()
        container._prompt_loader = FakePromptLoader()
        set_container(container)

        from api.endpoints.briefings import _get_briefing_service

        with pytest.raises(HTTPException) as exc_info:
            _get_briefing_service()
        assert exc_info.value.status_code == 503


__all__ = ["TestGetBriefingServiceContainerIntegration"]
