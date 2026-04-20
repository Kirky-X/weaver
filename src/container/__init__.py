# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Dependency injection container for the weaver application.

This package provides the Container as a facade combining four mixins:

- src.container.lifecycle  — startup/shutdown orchestration
- src.container.pools    — database and cache pool initialization
- src.container.services  — repositories, crawlers, fetchers, pipeline
- src.container.search   — search engine initialization
"""

from __future__ import annotations

import threading
from typing import Any

from config.settings import Settings
from core.observability import get_logger
from src.container.lifecycle import (
    ContainerLifecycleMixin,
    _handle_llm_failure_async,
    _handle_llm_usage_metrics,
)
from src.container.pools import ContainerPoolsMixin
from src.container.search import ContainerSearchMixin
from src.container.services import ContainerServicesMixin

log = get_logger(__name__)


class Container(
    ContainerLifecycleMixin,
    ContainerPoolsMixin,
    ContainerServicesMixin,
    ContainerSearchMixin,
):
    """Dependency injection container for the application.

    Manages lifecycle of all core services and provides them to
    the API layer and background workers.

    This class combines four mixins:
    - ContainerLifecycleMixin: startup/shutdown orchestration, LLM init
    - ContainerPoolsMixin: database and cache pool management
    - ContainerServicesMixin: repositories, crawlers, fetchers, pipeline
    - ContainerSearchMixin: search engine initialization
    """

    def __init__(self) -> None:
        self._settings: Settings | None = None
        self._strategy: Any = None
        self._cache_client: Any = None
        self._llm_client: Any = None
        self._prompt_loader: Any = None
        self._source_registry: Any = None
        self._source_config_repo: Any = None
        self._source_scheduler: Any = None
        self._article_repo: Any = None
        self._vector_repo: Any = None
        self._source_authority_repo: Any = None
        self._graph_entity_repo: Any = None
        self._graph_article_repo: Any = None
        self._graph_writer: Any = None
        self._graph_repo: Any = None
        self._entity_resolver: Any = None
        self._smart_fetcher: Any = None
        self._crawl4ai_fetcher: Any = None
        self._crawler: Any = None
        self._pipeline: Any = None
        self._pipeline_service: Any = None
        self._task_registry: Any = None
        self._deduplicator: Any = None
        self._event_bus: Any = None
        self._llm_failure_repo: Any = None
        self._llm_usage_buffer: Any = None
        self._llm_experience: Any = None
        self._live_config: Any = None
        self._smart_router: Any = None
        self._eval_runner: Any = None
        self._eval_compare_buffer: Any = None
        self._pending_sync_repo: Any = None
        self._scheduler_jobs_service: Any = None
        self._scheduler: Any = None
        self._community_updater: Any = None
        self._relation_type_normalizer: Any = None
        self._local_search_engine: Any = None
        self._global_search_engine: Any = None
        self._hybrid_engine: Any = None
        self._bm25_index_service: Any = None
        self._memory_service: Any = None
        self._shutdown: bool = False
        self._knowledge_cache: Any = None
        self._mc_sampler: Any = None
        self._causal_repo: Any = None
        self._causal_inference_service: Any = None
        self._processing_queue: Any = None
        self._pipeline_worker: Any = None
        self._llm_usage_repo: Any = None

    def configure(self, settings: Settings) -> Container:
        """Configure the container with settings."""
        self._settings = settings
        return self

    @property
    def settings(self) -> Settings:
        """Get settings."""
        if self._settings is None:
            raise RuntimeError("Container not configured. Call configure() first.")
        return self._settings


# ── Global container instance with thread-safe access ──────────────────────────

_container: Container | None = None
_container_lock = threading.Lock()


def get_container() -> Container:
    """Get the global container instance (thread-safe)."""
    with _container_lock:
        if _container is None:
            raise RuntimeError("Container not initialized. Create it in main.py first.")
        return _container


def set_container(container: Container) -> None:
    """Set the global container instance (thread-safe)."""
    global _container
    with _container_lock:
        _container = container


# ── Settings instance with thread-safe access ──────────────────────────────────

_settings_instance: Settings | None = None
_settings_lock = threading.Lock()


def get_settings() -> Settings:
    """Get settings instance (thread-safe)."""
    global _settings_instance
    with _settings_lock:
        if _settings_instance is None:
            from config.settings import Settings

            _settings_instance = Settings()
        return _settings_instance


def set_settings(settings: Settings) -> None:
    """Set settings instance (thread-safe)."""
    global _settings_instance
    with _settings_lock:
        _settings_instance = settings
