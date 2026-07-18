# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Container class — dependency injection facade combining four mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from config.settings import Settings
from container.lifecycle import (
    ContainerLifecycleMixin,
)
from container.pools import ContainerPoolsMixin
from container.search import ContainerSearchMixin
from container.services import ContainerServicesMixin
from core.observability import get_logger

if TYPE_CHECKING:
    from core.protocols.services import PipelineService, TaskRegistryService

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

    Combines four mixins:
    - ContainerLifecycleMixin: startup/shutdown orchestration, LLM init
    - ContainerPoolsMixin: database and cache pool management
    - ContainerServicesMixin: repositories, crawlers, fetchers, pipeline
    - ContainerSearchMixin: search engine initialization
    """

    def __init__(self) -> None:
        self._settings: Settings | None = None
        self._debug_mode: bool = False
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
        self._graph_writer: Any = None
        self._graph_repo: Any = None
        self._entity_resolver: Any = None
        self._smart_fetcher: Any = None
        self._crawler: Any = None
        self._pipeline: Any = None
        self._pipeline_service: PipelineService | None = None
        self._task_registry: TaskRegistryService | None = None
        self._deduplicator: Any = None
        self._simhash_dedup: Any = None
        self._retry_queue: Any = None
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
        self._saga_orchestrator: Any = None
        self._shutdown: bool = False
        self._knowledge_cache: Any = None
        self._mc_sampler: Any = None
        self._causal_repo: Any = None
        self._causal_inference_service: Any = None
        self._processing_queue: Any = None
        self._pipeline_worker: Any = None
        self._llm_usage_repo: Any = None
        self._conflict_detector: Any = None
        self._shift_detector: Any = None
        self._briefing_engine: Any = None
        self._cascade_classifier: Any = None
        self._gliner_extractor: Any = None
        self._gliner_warmup_task: Any = None
        self._trend_detector: Any = None
        self._sentiment_trend_analyzer: Any = None

    def configure(self, settings: Settings, debug: bool = False) -> Container:
        """Configure the container with settings."""
        self._settings = settings
        self._debug_mode = debug
        return self

    @property
    def settings(self) -> Settings:
        """Get settings."""
        if self._settings is None:
            raise RuntimeError("Container not configured. Call configure() first.")
        return self._settings

    def is_job_registered(self, job_id: str) -> bool:
        """Check if a scheduler job is registered.

        Args:
            job_id: The job identifier to check.

        Returns:
            True if the job is registered, False otherwise.

        """
        try:
            if self._scheduler is not None:
                jobs = self._scheduler.get_jobs()
                return any(j.id == job_id for j in jobs)
        except Exception:
            log.warning("scheduler_job_check_failed", exc_info=True)
        return False

    async def memory_diagnostics(self) -> dict[str, Any]:
        """Get memory service diagnostics.

        Returns:
            Dictionary with memory service statistics including:
            - temporal_event_count: Number of temporal events
            - causal_link_count: Number of causal links
            - pending_consolidation: Pending consolidation queue length
            - slow_path_enabled: Whether slow path is enabled
            - service_initialized: Whether memory service is initialized

        """
        result: dict[str, Any] = {
            "service_initialized": False,
            "temporal_event_count": 0,
            "causal_link_count": 0,
            "pending_consolidation": 0,
            "slow_path_enabled": False,
        }

        ms = self._memory_service
        if ms is not None:
            result["service_initialized"] = True
            try:
                result["temporal_event_count"] = await ms._temporal_repo.count_events()
                result["causal_link_count"] = await ms._causal_repo.count_causal_links()
                result["pending_consolidation"] = await ms._consolidation_queue.length()
                result["slow_path_enabled"] = ms._config.slow_path_enabled
            except Exception as exc:
                log.warning("memory_diagnostic_query_failed", error=str(exc))

        return result
