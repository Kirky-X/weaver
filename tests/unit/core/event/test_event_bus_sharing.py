# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for EventBus sharing between LLM and pipeline."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.db.query_builders import DatabaseType


class TestEventBusSharing:
    """Test that init_pipeline() creates EventBus and shares it."""

    def test_init_pipeline_reuses_global_event_bus(self):
        """Test init_pipeline() binds the module-level singleton when unset.

        The container must never fork the bus: sync emitters (circuit
        breakers) publish to ``core.event.event_bus``, so every subscriber
        must live on that same instance.
        """
        import inspect

        from config.settings import Settings
        from container import Container

        settings = Settings()
        container = Container().configure(settings)

        source = inspect.getsource(container.init_pipeline)

        assert "from core.event import event_bus" in source, (
            "init_pipeline() must import the module-level event_bus singleton"
        )
        assert "= EventBus()" not in source, (
            "init_pipeline() must not instantiate a private EventBus"
        )

    def test_init_pipeline_checks_existing_event_bus(self):
        """Test init_pipeline() checks if self._event_bus already exists.

        Verifies that init_pipeline() does NOT create a new EventBus
        if one was already created.
        """
        import inspect

        from config.settings import Settings
        from container import Container

        settings = Settings()
        container = Container().configure(settings)

        pipeline_source = inspect.getsource(container.init_pipeline)
        assert "if self._event_bus is None:" in pipeline_source, (
            "init_pipeline must check if self._event_bus already exists before creating one"
        )
        assert "self._event_bus = EventBus()" not in pipeline_source, (
            "init_pipeline must never fork the bus with a private instance"
        )

    @pytest.mark.asyncio
    async def test_init_pipeline_reuses_event_bus(self):
        """Test init_pipeline() does NOT create a new EventBus if one already exists."""
        from config.settings import Settings
        from container import Container

        settings = Settings()
        container = Container().configure(settings)

        # Pre-set an event bus
        existing_bus = MagicMock()
        container._event_bus = existing_bus
        container._llm_client = MagicMock()
        container._prompt_loader = MagicMock()

        # Mock strategy to avoid database initialization
        mock_strategy = MagicMock()
        mock_strategy.graph_pool = None
        mock_strategy.relational_pool = MagicMock()
        mock_strategy.relational_type = DatabaseType.POSTGRES  # Needed for VectorRepo QueryBuilder
        container._strategy = mock_strategy

        mock_spacy = MagicMock()
        mock_token_budget = MagicMock()

        with (
            patch(
                "core.llm.config.token_budget.TokenBudgetManager", return_value=mock_token_budget
            ),
            patch("modules.processing.nlp.spacy_extractor.SpacyExtractor", return_value=mock_spacy),
            patch("modules.processing.pipeline.graph.Pipeline") as mock_pipeline_cls,
            patch.object(container, "_cache_client", MagicMock()),
        ):
            mock_pipeline_cls.return_value = MagicMock()
            await container.init_pipeline()

            # The existing bus should be reused
            assert container._event_bus is existing_bus

    @pytest.mark.asyncio
    async def test_init_pipeline_creates_event_bus_when_none_exists(self):
        """Test init_pipeline() creates EventBus only when self._event_bus is None."""
        from config.settings import Settings
        from container import Container

        settings = Settings()
        container = Container().configure(settings)

        container._event_bus = None
        container._llm_client = MagicMock()
        container._prompt_loader = MagicMock()

        # Mock strategy to avoid database initialization
        mock_strategy = MagicMock()
        mock_strategy.graph_pool = None
        mock_strategy.relational_pool = MagicMock()
        mock_strategy.relational_type = DatabaseType.POSTGRES  # Needed for VectorRepo QueryBuilder
        container._strategy = mock_strategy

        mock_spacy = MagicMock()
        mock_token_budget = MagicMock()

        with (
            patch(
                "core.llm.config.token_budget.TokenBudgetManager", return_value=mock_token_budget
            ),
            patch("modules.processing.nlp.spacy_extractor.SpacyExtractor", return_value=mock_spacy),
            patch("modules.processing.pipeline.graph.Pipeline") as mock_pipeline_cls,
        ):
            mock_pipeline_cls.return_value = MagicMock()

            await container.init_pipeline()

            # The module-level singleton must be bound, not a fresh instance.
            from core.event import event_bus as global_event_bus

            assert container._event_bus is global_event_bus

    def test_startup_order_passes_event_bus_to_cleanup_handler(self):
        """Test startup() calls subscribe() on the same event_bus used by pipeline."""
        import inspect

        from config.settings import Settings
        from container import Container
        from container.lifecycle import _handle_llm_failure_async

        settings = Settings()
        container = Container().configure(settings)

        # Check startup() source contains event_bus subscription logic
        source = inspect.getsource(container.startup)
        assert "_event_bus.subscribe" in source
        assert "LLMFailureEvent" in source

        # Check _handle_llm_failure_async exists and is callable
        assert callable(_handle_llm_failure_async)
