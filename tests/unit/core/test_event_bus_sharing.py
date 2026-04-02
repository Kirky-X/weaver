# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for EventBus sharing between LLM and pipeline."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestEventBusSharing:
    """Test that init_pipeline() creates EventBus and shares it."""

    def test_init_pipeline_creates_event_bus(self):
        """Test init_pipeline() creates EventBus as self._event_bus.

        Verifies that EventBus is created in init_pipeline() when
        self._event_bus is None.
        """
        import inspect

        from config.settings import Settings
        from container import Container

        settings = Settings()
        container = Container().configure(settings)

        source = inspect.getsource(container.init_pipeline)

        # Verify EventBus is created in init_pipeline
        assert "self._event_bus = EventBus()" in source, (
            "EventBus must be assigned to self._event_bus in init_pipeline(). "
            "This allows the pipeline to use a shared instance."
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
        assert (
            "if self._event_bus is None:" in pipeline_source
        ), "init_pipeline must check if self._event_bus already exists before creating one"
        assert (
            "self._event_bus = EventBus()" in pipeline_source
        ), "init_pipeline may create EventBus only when self._event_bus is None"

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

        mock_spacy = MagicMock()
        mock_token_budget = MagicMock()

        with (
            patch("core.llm.token_budget.TokenBudgetManager", return_value=mock_token_budget),
            patch("modules.nlp.spacy_extractor.SpacyExtractor", return_value=mock_spacy),
            patch("modules.processing.pipeline.graph.Pipeline") as mock_pipeline_cls,
            patch.object(container, "_redis_client", MagicMock()),
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

        mock_spacy = MagicMock()
        mock_token_budget = MagicMock()

        with (
            patch("core.llm.token_budget.TokenBudgetManager", return_value=mock_token_budget),
            patch("modules.nlp.spacy_extractor.SpacyExtractor", return_value=mock_spacy),
            patch("modules.processing.pipeline.graph.Pipeline") as mock_pipeline_cls,
            patch("container.EventBus") as mock_event_bus_cls,
        ):
            new_bus = MagicMock()
            mock_event_bus_cls.return_value = new_bus
            mock_pipeline_cls.return_value = MagicMock()

            await container.init_pipeline()

            # EventBus SHOULD be instantiated since it was None
            mock_event_bus_cls.assert_called_once()
            assert container._event_bus is new_bus

    def test_startup_order_passes_event_bus_to_cleanup_handler(self):
        """Test startup() calls subscribe() on the same event_bus used by pipeline."""
        import inspect

        from config.settings import Settings
        from container import Container, _handle_llm_failure_async

        settings = Settings()
        container = Container().configure(settings)

        # Check startup() source contains event_bus subscription logic
        source = inspect.getsource(container.startup)
        assert "_event_bus.subscribe" in source
        assert "LLMFailureEvent" in source

        # Check _handle_llm_failure_async exists and is callable
        assert callable(_handle_llm_failure_async)
