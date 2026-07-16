# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Pytest configuration and shared fixtures for pipeline tests."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.domain.models import RawArticle


@pytest.fixture
def sample_raw():
    """Create sample RawArticle for pipeline node tests."""
    return RawArticle(
        url="https://example.com/test-article",
        title="Test Article Title",
        body="Test article body content.",
        source="test_source",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_budget():
    """Mock token budget manager for pipeline tests."""
    budget = MagicMock()
    budget.truncate = MagicMock(
        side_effect=lambda text, cp: text[:2000] if len(text) > 2000 else text
    )
    return budget


@pytest.fixture
def mock_prompt_loader():
    """Mock prompt loader for pipeline tests."""
    loader = MagicMock()
    loader.get_version = MagicMock(return_value="1.0.0")
    return loader


@pytest.fixture
def mock_event_bus():
    """Mock event bus for pipeline tests."""
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def sample_article_raw(sample_raw):
    """Alias for sample_raw for backward compatibility with root conftest.py."""
    return sample_raw


def make_pipeline_deps(
    *,
    llm=None,
    budget=None,
    prompt_loader=None,
    event_bus=None,
    spacy=None,
    vector_repo=None,
    article_repo=None,
    graph_writer=None,
    source_auth_repo=None,
    entity_resolver=None,
    cache_client=None,
    community_updater=None,
    saga_orchestrator=None,
    relation_type_normalizer=None,
    sentiment_analyzer=None,
    cascade_classifier=None,
    gliner_extractor=None,
    mc_sampler=None,
    fake_news_detector=None,
):
    """Build PipelineDeps from flat kwargs (legacy constructor compatibility).

    Helper for tests that still use the pre-refactor parameter style.
    """
    from modules.processing.pipeline.deps import (
        PipelineAnalyzers,
        PipelineDeps,
        PipelineInfra,
        PipelineNlpTools,
        PipelineRepos,
    )

    return PipelineDeps(
        llm=llm or MagicMock(),
        budget=budget or MagicMock(),
        prompt_loader=prompt_loader or MagicMock(),
        event_bus=event_bus or MagicMock(),
        repos=PipelineRepos(
            vector_repo=vector_repo,
            article_repo=article_repo,
            graph_writer=graph_writer,
            source_auth_repo=source_auth_repo,
        ),
        nlp=PipelineNlpTools(
            spacy=spacy,
            entity_resolver=entity_resolver,
            gliner_extractor=gliner_extractor,
            relation_type_normalizer=relation_type_normalizer,
        ),
        analyzers=PipelineAnalyzers(
            sentiment_analyzer=sentiment_analyzer,
            cascade_classifier=cascade_classifier,
            fake_news_detector=fake_news_detector,
            mc_sampler=mc_sampler,
        ),
        infrastructure=PipelineInfra(
            cache_client=cache_client,
            community_updater=community_updater,
            saga_orchestrator=saga_orchestrator,
        ),
    )


def make_pipeline(
    *,
    llm=None,
    budget=None,
    prompt_loader=None,
    event_bus=None,
    settings=None,
    spacy=None,
    vector_repo=None,
    article_repo=None,
    graph_writer=None,
    source_auth_repo=None,
    entity_resolver=None,
    cache_client=None,
    community_updater=None,
    phase1_concurrency=None,
    phase3_concurrency=None,
    relation_type_normalizer=None,
    sentiment_analyzer=None,
    cascade_classifier=None,
    gliner_extractor=None,
    mc_sampler=None,
    fake_news_detector=None,
    saga_orchestrator=None,
    debug=False,
):
    """Build a Pipeline instance using the new PipelineDeps API.

    Accepts the legacy constructor signature for backward compatibility with
    pre-refactor tests. ``phase1_concurrency`` / ``phase3_concurrency`` are
    ignored (use ``settings`` instead).
    """
    from modules.processing.pipeline.graph import Pipeline

    deps = make_pipeline_deps(
        llm=llm,
        budget=budget,
        prompt_loader=prompt_loader,
        event_bus=event_bus,
        spacy=spacy,
        vector_repo=vector_repo,
        article_repo=article_repo,
        graph_writer=graph_writer,
        source_auth_repo=source_auth_repo,
        entity_resolver=entity_resolver,
        cache_client=cache_client,
        community_updater=community_updater,
        saga_orchestrator=saga_orchestrator,
        relation_type_normalizer=relation_type_normalizer,
        sentiment_analyzer=sentiment_analyzer,
        cascade_classifier=cascade_classifier,
        gliner_extractor=gliner_extractor,
        mc_sampler=mc_sampler,
        fake_news_detector=fake_news_detector,
    )
    return Pipeline(deps=deps, settings=settings, debug=debug)
