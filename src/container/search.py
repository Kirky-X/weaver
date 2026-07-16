# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Search engine initialization for the container."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.constants import DatabaseType
from modules.knowledge.search import GlobalSearchEngine, HybridSearchEngine, LocalSearchEngine

if TYPE_CHECKING:
    from core.llm import LLMClient


class ContainerSearchMixin:
    """Search engine management mixin.

    Provides initialization and access to local, global, and hybrid search engines,
    as well as BM25 index management.
    """

    # ── Private attributes (defined in Container.__init__) ─────────
    _llm_client: LLMClient | None
    _strategy: Any
    _local_search_engine: LocalSearchEngine | None
    _global_search_engine: GlobalSearchEngine | None
    _hybrid_engine: HybridSearchEngine | None
    _bm25_index_service: Any
    _settings: Any

    # ── Search Engines ───────────────────────────────────────────────

    def init_search_engines(self) -> tuple[LocalSearchEngine, GlobalSearchEngine] | None:
        """Initialize search engines (requires graph pool to be available)."""
        graph_pool = self.graph_pool()
        if graph_pool is None or self._llm_client is None:
            return None
        if self._strategy is None:
            return None

        # Build context builders based on graph type
        if self._strategy.graph_type == DatabaseType.LADYBUG.value:
            from modules.knowledge.search.context.ladybug_global_context import (
                LadybugGlobalContextBuilder,
            )
            from modules.knowledge.search.context.ladybug_local_context import (
                LadybugLocalContextBuilder,
            )

            local_builder = LadybugLocalContextBuilder(
                graph_pool=graph_pool,
                article_repo=self.article_repo(),
                default_max_tokens=8000,
            )
            global_builder = LadybugGlobalContextBuilder(
                graph_pool=graph_pool,
                default_max_tokens=12000,
                llm_client=self._llm_client,
            )
        else:
            # Neo4j (default)
            from modules.knowledge.search.context.global_context import GlobalContextBuilder
            from modules.knowledge.search.context.local_context import LocalContextBuilder

            local_builder = LocalContextBuilder(
                graph_pool=graph_pool,
                article_repo=self.article_repo(),
                default_max_tokens=8000,
            )
            global_builder = GlobalContextBuilder(
                graph_pool=graph_pool,
                default_max_tokens=12000,
                llm_client=self._llm_client,
            )

        if self._local_search_engine is None:
            self._local_search_engine = LocalSearchEngine(
                llm=self._llm_client,
                context_builder=local_builder,
            )
        if self._global_search_engine is None:
            self._global_search_engine = GlobalSearchEngine(
                llm=self._llm_client,
                context_builder=global_builder,
                local_engine=self._local_search_engine,
                search_settings=self._settings.search,
            )
        return (self._local_search_engine, self._global_search_engine)

    def local_search_engine(self) -> LocalSearchEngine | None:
        """Get local search engine (or None if unavailable)."""
        if self._local_search_engine is None and self.graph_pool() is not None:
            self.init_search_engines()
        return self._local_search_engine

    def global_search_engine(self) -> GlobalSearchEngine | None:
        """Get global search engine (or None if unavailable)."""
        if self._global_search_engine is None and self.graph_pool() is not None:
            self.init_search_engines()
        return self._global_search_engine

    def hybrid_search_engine(self) -> HybridSearchEngine | None:
        """Get hybrid search engine (or None if unavailable)."""
        from core.observability import get_logger
        from modules.knowledge.search import HybridSearchConfig
        from modules.knowledge.search.retrievers.bm25_retriever import BM25Retriever

        log = get_logger(__name__)

        if self._hybrid_engine is None:
            # Trigger vector_repo lazy load
            self.vector_repo()
            if self._vector_repo is None:
                return None

            bm25_retriever = BM25Retriever(self.relational_pool())

            # Initialize Flashrank reranker
            reranker = None
            if self._settings.search.rerank_enabled:
                try:
                    from modules.knowledge.search.rerankers.flashrank_reranker import (
                        FlashrankReranker,
                    )

                    reranker = FlashrankReranker(
                        model_name=self._settings.search.rerank_model,
                        enabled=True,
                    )
                except Exception as exc:
                    log.warning("flashrank_reranker_init_failed", error=str(exc), exc_info=True)

            # Initialize MMR reranker
            mmr_reranker = None
            if self._settings.search.mmr_enabled:
                try:
                    from modules.knowledge.search.rerankers.mmr_reranker import MMRReranker

                    mmr_reranker = MMRReranker(
                        lambda_param=self._settings.search.mmr_lambda,
                        similarity_mode=self._settings.search.mmr_similarity_mode,
                    )
                except Exception as exc:
                    log.warning("mmr_reranker_init_failed", error=str(exc), exc_info=True)

            self._hybrid_engine = HybridSearchEngine(
                vector_repo=self._vector_repo,
                bm25_retriever=bm25_retriever,
                reranker=reranker,
                mmr_reranker=mmr_reranker,
                config=HybridSearchConfig(),
            )
        return self._hybrid_engine

    async def _init_bm25_index(self) -> None:
        """Initialize BM25 index service and build index if needed."""
        from core.observability import get_logger
        from modules.knowledge.search.retrievers.bm25_index_service import BM25IndexService

        log = get_logger(__name__)

        if self._bm25_index_service is not None:
            return

        try:
            # Trigger hybrid engine initialization (lazy load)
            hybrid_engine = self.hybrid_search_engine()
            bm25_retriever = hybrid_engine._bm25_retriever if hybrid_engine else None

            if bm25_retriever is not None:
                self._bm25_index_service = BM25IndexService(
                    relational_pool=self.relational_pool(),
                    bm25_retriever=bm25_retriever,
                )

                # Build index on startup if empty
                if not bm25_retriever.is_initialized:
                    count = await self._bm25_index_service.build_full_index()
                    if count > 0:
                        log.info("bm25_index_built_on_startup", documents=count)
                    else:
                        log.info("bm25_index_build_skipped_no_articles")
        except Exception as e:
            log.error("bm25_index_init_failed", error=str(e), exc_info=True)
