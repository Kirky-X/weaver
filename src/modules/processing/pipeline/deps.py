# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Pipeline dependency dataclasses.

Groups the 23 constructor parameters of ``Pipeline`` into a small number of
typed containers so that the pipeline signature stays stable as new
dependencies are added.

Usage::

    from modules.processing.pipeline.deps import PipelineDeps, PipelineRepos

    deps = PipelineDeps(
        llm=llm_client,
        budget=budget,
        prompt_loader=prompt_loader,
        event_bus=event_bus,
        repos=PipelineRepos(vector_repo=..., article_repo=...),
        ...
    )
    pipeline = Pipeline(deps=deps, settings=settings)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.event import EventBus
    from core.llm.client import LLMClient
    from core.llm.config.token_budget import TokenBudgetManager
    from core.prompt.loader import PromptLoader
    from core.protocols import (
        ArticleRepository,
        CachePool,
        GraphWriter,
        SourceAuthorityRepository,
        VectorRepository,
    )
    from modules.analytics.sentiment_analyzer import SentimentAnalyzer
    from modules.analytics.storage import AnalyticsStorage
    from modules.knowledge.graph.community.updater import (
        IncrementalCommunityUpdater,
    )
    from modules.knowledge.graph.entity_resolver import EntityResolver
    from modules.processing.nlp.spacy_extractor import SpacyExtractor


@dataclass
class PipelineRepos:
    """Repository dependencies used by the pipeline for persistence."""

    vector_repo: VectorRepository | None = None
    article_repo: ArticleRepository | None = None
    graph_writer: GraphWriter | None = None
    source_auth_repo: SourceAuthorityRepository | None = None


@dataclass
class PipelineNlpTools:
    """NLP tooling dependencies (entity extraction / resolution)."""

    spacy: SpacyExtractor | None = None
    entity_resolver: EntityResolver | None = None
    gliner_extractor: Any | None = None
    relation_type_normalizer: Any | None = None


@dataclass
class PipelineAnalyzers:
    """Analyzer dependencies (classification / sentiment / fake news)."""

    sentiment_analyzer: SentimentAnalyzer | None = None
    cascade_classifier: Any | None = None
    fake_news_detector: Any | None = None
    mc_sampler: Any | None = None


@dataclass
class PipelineInfra:
    """Infrastructure dependencies (cache / community / saga)."""

    cache_client: CachePool | None = None
    community_updater: IncrementalCommunityUpdater | None = None
    saga_orchestrator: Any | None = None
    # T003: AnalyticsStorage for SentimentTrackerNode article-level tracking.
    # None when relational pool is unavailable; pipeline skips the node.
    sentiment_shift_repo: AnalyticsStorage | None = None


@dataclass
class PipelineDeps:
    """Aggregate all pipeline dependencies.

    Fields:
        llm: Unified LLM client.
        budget: Token budget manager.
        prompt_loader: Prompt template loader.
        event_bus: Event bus for publishing pipeline events.
        repos: Repository group (PG / vector / graph).
        nlp: NLP tooling group.
        analyzers: Analyzer group.
        infrastructure: Infrastructure group (cache / community / saga).
    """

    llm: LLMClient
    budget: TokenBudgetManager
    prompt_loader: PromptLoader
    event_bus: EventBus
    repos: PipelineRepos = field(default_factory=PipelineRepos)
    nlp: PipelineNlpTools = field(default_factory=PipelineNlpTools)
    analyzers: PipelineAnalyzers = field(default_factory=PipelineAnalyzers)
    infrastructure: PipelineInfra = field(default_factory=PipelineInfra)
