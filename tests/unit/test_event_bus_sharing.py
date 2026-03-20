# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for EventBus sharing between LLM and pipeline."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestEventBusSharing:
    """Test that init_llm() and init_pipeline() share the same EventBus instance."""

    def test_init_llm_stores_event_bus_as_instance_variable(self):
        """Test init_llm() stores EventBus as self._event_bus, not a local variable.

        Verifies ISSUE-2 fix: EventBus must be stored as self._event_bus,
        not as a local variable, so init_pipeline() can share the same instance.
        """
        import inspect

        from config.settings import Settings
        from container import Container

        settings = Settings()
        container = Container().configure(settings)

        source = inspect.getsource(container.init_llm)

        # ISSUE-2 fix verification: EventBus must be assigned to self._event_bus
        # (not a local variable), so init_pipeline() can reuse it.
        assert "self._event_bus = EventBus()" in source, (
            "EventBus must be assigned to self._event_bus (instance variable), "
            "not a local variable. This is the ISSUE-2 fix."
        )
        # Verify LLMQueueManager receives event_bus as kwarg
        assert (
            "event_bus=self._event_bus" in source
        ), "LLMQueueManager must receive event_bus=self._event_bus"
        # Verify the event bus is NOT created locally in init_pipeline without checking self._event_bus
        pipeline_source = inspect.getsource(container.init_pipeline)
        assert (
            "if self._event_bus is None:" in pipeline_source
        ), "init_pipeline must check if self._event_bus already exists before creating one"
        assert (
            "self._event_bus = EventBus()" in pipeline_source
        ), "init_pipeline may create EventBus only when self._event_bus is None"

    @pytest.mark.asyncio
    async def test_init_pipeline_reuses_event_bus_from_init_llm(self):
        """Test init_pipeline() does NOT create a new EventBus if one already exists."""
        from config.settings import Settings
        from container import Container

        settings = Settings()
        container = Container().configure(settings)

        # Pre-set an event bus (simulates init_llm() having been called first)
        existing_bus = MagicMock()
        container._event_bus = existing_bus
        container._llm_client = MagicMock()

        mock_spacy = MagicMock()
        mock_token_budget = MagicMock()

        with (
            patch("container.TokenBudgetManager", return_value=mock_token_budget),
            patch("modules.nlp.spacy_extractor.SpacyExtractor", return_value=mock_spacy),
            patch.object(container, "vector_repo", return_value=MagicMock()),
            patch.object(container, "article_repo", return_value=MagicMock()),
            patch.object(container, "neo4j_writer", return_value=MagicMock()),
            patch.object(container, "source_authority_repo", return_value=MagicMock()),
            patch.object(container, "entity_resolver", return_value=MagicMock()),
            patch.object(container, "_redis_client", MagicMock()),
            patch("container.EventBus") as mock_event_bus_cls,
        ):
            await container.init_pipeline()

            # EventBus should NOT be instantiated in init_pipeline()
            mock_event_bus_cls.assert_not_called()
            # The existing bus from init_llm() should be reused
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

        mock_spacy = MagicMock()
        mock_token_budget = MagicMock()
        new_bus = MagicMock()

        with (
            patch("container.TokenBudgetManager", return_value=mock_token_budget),
            patch("modules.nlp.spacy_extractor.SpacyExtractor", return_value=mock_spacy),
            patch.object(container, "vector_repo", return_value=MagicMock()),
            patch.object(container, "article_repo", return_value=MagicMock()),
            patch.object(container, "neo4j_writer", return_value=MagicMock()),
            patch.object(container, "source_authority_repo", return_value=MagicMock()),
            patch.object(container, "entity_resolver", return_value=MagicMock()),
            patch.object(container, "_redis_client", MagicMock()),
            patch("container.EventBus", return_value=new_bus) as mock_event_bus_cls,
        ):
            await container.init_pipeline()

            # EventBus SHOULD be instantiated in init_pipeline() since it's None
            mock_event_bus_cls.assert_called_once()
            assert container._event_bus is new_bus

    def test_startup_order_passes_event_bus_to_cleanup_handler(self):
        """Test startup() calls subscribe() on the same event_bus used by LLM."""
        # This test verifies the full chain: init_llm sets self._event_bus,
        # then startup() registers the LLM failure handler on that same bus.
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
