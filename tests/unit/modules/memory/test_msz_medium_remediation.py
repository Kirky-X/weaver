# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Regression tests for memory MEDIUM findings."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.memory.core.graph_types import AggregationType, IntentType, OutputMode


@pytest.mark.unit
def test_353_empty_article_id_warns_not_raise():
    from modules.memory.core import event_node as en_mod
    from modules.memory.core.event_node import EventNode

    with patch.object(en_mod.log, "warning") as mock_warn:
        node = EventNode.from_pipeline_state({})
    assert node.id == ""
    mock_warn.assert_called_once()
    assert mock_warn.call_args[0][0] == "event_node_missing_article_id"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_354_programming_error_fails_without_retry():
    from modules.memory.evolution.fast_path import SynapticIngestionService

    temporal = MagicMock()
    temporal.append_to_chain = AsyncMock(side_effect=TypeError("bad event"))
    service = SynapticIngestionService(temporal_repo=temporal)
    state = {"article_id": "a1", "cleaned": {"title": "t", "content": "c"}}
    result = await service.ingest(state)
    assert result is None
    assert temporal.append_to_chain.call_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_355_cancelled_error_propagates():
    from modules.memory.evolution.fast_path import SynapticIngestionService

    temporal = MagicMock()
    temporal.append_to_chain = AsyncMock(side_effect=asyncio.CancelledError())
    service = SynapticIngestionService(temporal_repo=temporal)
    state = {"article_id": "a1", "cleaned": {"title": "t", "content": "c"}}
    with pytest.raises(asyncio.CancelledError):
        await service.ingest(state)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_359_max_depth_validated_and_prevents_included():
    from modules.memory.graphs.causal import CausalGraphRepo

    pool = MagicMock()
    pool.database_type = "neo4j"
    pool.execute_query = AsyncMock(return_value=[])
    repo = CausalGraphRepo(pool=pool)
    with pytest.raises(ValueError):
        await repo.get_causal_chain("e1", max_depth="1) MATCH (n) DETACH DELETE n //")
    await repo.get_causal_chain("e1", max_depth=100)
    query = pool.execute_query.call_args[0][0]
    assert "*1..10" in query
    assert "PREVENTS" in query


@pytest.mark.unit
@pytest.mark.asyncio
async def test_362_causes_effects_include_prevents_neo4j():
    from modules.memory.graphs.causal import CausalGraphRepo

    pool = MagicMock()
    pool.database_type = "neo4j"
    pool.execute_query = AsyncMock(return_value=[])
    repo = CausalGraphRepo(pool=pool)
    await repo.get_causes("e1")
    assert "PREVENTS" in pool.execute_query.call_args[0][0]
    await repo.get_effects("e1")
    assert "PREVENTS" in pool.execute_query.call_args[0][0]


@pytest.mark.unit
def test_367_adapter_init_without_set_cached():
    from modules.memory.retrieval.adaptive_search import _IntentGraphAdapter

    adapter = _IntentGraphAdapter()
    assert adapter.get_neighbors("missing") == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_368_cache_hit_marks_flag():
    from modules.memory.retrieval.adaptive_search import AdaptiveSearchEngine

    temporal = MagicMock()
    temporal.search_temporal_events = AsyncMock(return_value=[])
    causal = MagicMock()
    embedding = MagicMock()
    embedding.embed = AsyncMock(return_value=[0.1])
    classifier = MagicMock()
    cluster = MagicMock()
    cluster.id = "kc_1"
    cluster.content = "cached answer"
    cache = MagicMock()
    cache.find_similar_cluster = AsyncMock(return_value=cluster)
    cache.update_hotness = AsyncMock(return_value=None)
    engine = AdaptiveSearchEngine(
        temporal_repo=temporal,
        causal_repo=causal,
        embedding_service=embedding,
        intent_classifier=classifier,
        knowledge_cache=cache,
    )
    results = await engine.search("q")
    assert results[0]["score"] == 1.0
    assert results[0]["source"] == "cache"
    assert results[0]["cache_hit"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_370_confidence_and_facts_coerced():
    from modules.memory.retrieval.entity_aggregator import EntityAggregator

    repo = MagicMock()
    repo.get_entity_neighborhood = AsyncMock(
        return_value={"center": "E", "events": [], "related_entities": [], "relations": []}
    )
    llm = MagicMock()
    llm.call_at = AsyncMock(
        return_value={"facts": "single fact string", "confidence": "high", "entity_type": "ORG"}
    )
    agg = EntityAggregator(entity_repo=repo, llm=llm)
    result = await agg.aggregate(entity_name="E", aggregation_type=AggregationType.FACTS)
    assert result.facts == ["single fact string"]
    assert result.confidence == 0.5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_371_entity_name_fallback_when_center_missing():
    from modules.memory.retrieval.entity_aggregator import EntityAggregator

    repo = MagicMock()
    repo.get_entity_neighborhood = AsyncMock(return_value={"events": [{"x": 1}]})
    llm = MagicMock()
    agg = EntityAggregator(entity_repo=repo, llm=llm)
    result = await agg.aggregate(entity_name="Fallback", aggregation_type=AggregationType.COUNT)
    assert result.entity_name == "Fallback"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_373_budget_overflow_includes_first_truncated():
    from modules.memory.retrieval.narrative_synthesizer import NarrativeSynthesizer

    synth = NarrativeSynthesizer(llm=MagicMock(), max_context_tokens=10)
    nodes = [{"id": "n1", "content": "X" * 5000, "score": 0.9, "source": "s"}]
    result = await synth.synthesize(query="q", context_nodes=nodes, mode=OutputMode.CONTEXT)
    assert result.node_count == 1
    assert "[truncated]" in result.output


@pytest.mark.unit
@pytest.mark.asyncio
async def test_374_llm_fallback_labeled_context():
    from modules.memory.retrieval.narrative_synthesizer import NarrativeSynthesizer

    llm = MagicMock()
    llm.call_at = AsyncMock(side_effect=RuntimeError("boom"))
    synth = NarrativeSynthesizer(llm=llm)
    nodes = [{"id": "n1", "content": "hello context", "source": "s"}]
    result = await synth.synthesize(query="q", context_nodes=nodes, mode=OutputMode.NARRATIVE)
    assert result.mode == OutputMode.CONTEXT
    assert "hello context" in result.output


@pytest.mark.unit
def test_232_package_exports():
    import modules.memory.graphs as g

    assert set(g.__all__) == {"BaseGraphRepo", "CausalGraphRepo", "TemporalGraphRepo"}
    assert g.BaseGraphRepo is not None
    assert "temporal and causal" in g.__doc__


@pytest.mark.unit
def test_099_cosine_range_documents_negative():
    from modules.memory.core.traversal import cosine_similarity

    assert "[-1, 1]" in (cosine_similarity.__doc__ or "")
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_100_duplicate_enqueue_suppressed():
    from modules.memory.evolution.queue import ConsolidationQueue

    redis = MagicMock()
    redis.lpush = AsyncMock(return_value=1)
    redis.delete = AsyncMock(return_value=1)
    redis.lrange = AsyncMock(return_value=[])
    calls = {"n": 0}

    async def fake_set_nx(key, value, ex=None):
        calls["n"] += 1
        return calls["n"] == 1

    redis.set_nx = fake_set_nx
    queue = ConsolidationQueue(redis=redis, key_prefix="test:dedup")
    assert await queue.enqueue("e1") is True
    assert await queue.enqueue("e1") is True
    assert redis.lpush.call_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_103_invalid_output_mode_raises():
    from modules.memory.integration.memory_service import MemoryIntegrationService

    pool = MagicMock()
    pool.database_type = "neo4j"
    llm = MagicMock()
    cache = MagicMock()
    cache.lpush = AsyncMock(return_value=1)
    cache.rpop = AsyncMock(return_value=None)
    cache.llen = AsyncMock(return_value=0)
    embedding = MagicMock()
    classifier = MagicMock()
    entity_repo = MagicMock()
    service = MemoryIntegrationService(
        graph_pool=pool,
        llm_client=llm,
        cache=cache,
        embedding_service=embedding,
        intent_classifier=classifier,
        entity_repo=entity_repo,
    )
    with pytest.raises(ValueError):
        await service.search_with_context(query="q", output_mode="narratie")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_077_normalized_match_survives_whitespace_drift():
    import json

    from modules.memory.causal.causal_inference import CausalInferenceService

    pool = MagicMock()
    pool.database_type = "neo4j"
    llm = MagicMock()
    payload = json.dumps(
        [{"source": "A", "target": "B", "type": "CAUSES", "confidence": 0.9, "evidence": "e"}]
    )
    llm.call_at = AsyncMock(return_value=payload)
    service = CausalInferenceService(pool=pool, llm_client=llm, causal_repo=MagicMock())
    relations = [{"source": "A ", "target": "B", "relation_type": "合作"}]
    inferences = await service._infer_batch(relations)
    assert len(inferences) == 1
    assert inferences[0].source_entity == "A"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_079_ladybug_count_sums_per_table():
    from modules.memory.graphs.causal import CausalGraphRepo

    pool = MagicMock()
    pool.database_type = "ladybug"
    pool.execute_query = AsyncMock(return_value=[{"count": 2}])
    repo = CausalGraphRepo(pool=pool)
    assert await repo.count_causal_links() == 6
    assert pool.execute_query.call_count == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_080_fallback_populates_per_search_cache():
    from modules.memory.retrieval.adaptive_search import AdaptiveSearchEngine

    temporal = MagicMock()
    temporal.get_temporal_chain = AsyncMock(
        return_value=[{"id": "a", "content": "ca"}, {"id": "b", "content": "cb"}]
    )
    temporal.search_temporal_events = AsyncMock(return_value=[])
    engine = AdaptiveSearchEngine(
        temporal_repo=temporal,
        causal_repo=MagicMock(),
        embedding_service=MagicMock(),
        intent_classifier=MagicMock(),
    )
    cache: dict = {}
    first = await engine._get_event_data("a", cache)
    assert first == {"id": "a", "content": "ca"}
    assert set(cache) == {"a", "b"}
    assert temporal.get_temporal_chain.call_count == 1
    second = await engine._get_event_data("b", cache)
    assert second == {"id": "b", "content": "cb"}
    assert temporal.get_temporal_chain.call_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_082_enrich_runs_concurrently_and_preserves_order():
    from modules.memory.retrieval.response_builder import SearchResponseBuilder

    aggregator = MagicMock()

    async def fake_aggregate(entity_name, aggregation_type, hops=2):
        await asyncio.sleep(0.01)
        m = MagicMock()
        m.entity_name = entity_name
        m.entity_type = "T"
        m.facts = [f"fact-{entity_name}"]
        m.count = 1
        m.confidence = 0.5
        return m

    aggregator.aggregate = fake_aggregate
    builder = SearchResponseBuilder(
        search_engine=MagicMock(),
        entity_aggregator=aggregator,
        synthesizer=MagicMock(),
        llm=MagicMock(),
    )
    results = await builder._enrich_entities(
        query="q", search_results=[], entity_names=["e1", "e2", "e3"]
    )
    assert [r["entity"] for r in results] == ["e1", "e2", "e3"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_064_before_after_validated():
    from modules.memory.graphs.temporal import TemporalGraphRepo

    pool = MagicMock()
    pool.database_type = "neo4j"
    pool.execute_query = AsyncMock(return_value=[])
    repo = TemporalGraphRepo(pool=pool)
    with pytest.raises(TypeError):
        await repo.get_neighbors("e1", before="1) MATCH (n) DETACH DELETE n //")
    with pytest.raises(ValueError):
        await repo.get_neighbors("e1", before=0)
    await repo.get_neighbors("e1", before=2, after=3)
    query = pool.execute_query.call_args[0][0]
    assert "*1..2" in query
    assert "*1..3" in query


@pytest.mark.unit
@pytest.mark.asyncio
async def test_065_exception_not_echoed_in_output():
    from modules.memory.retrieval.narrative_synthesizer import NarrativeSynthesizer

    synth = NarrativeSynthesizer(llm=MagicMock())
    synth._synthesize_context = AsyncMock(side_effect=RuntimeError("secret-token-xyz"))
    result = await synth.synthesize(
        query="q", context_nodes=[{"id": "1", "content": "c"}], mode=OutputMode.CONTEXT
    )
    assert "secret-token-xyz" not in result.output
    assert "Synthesis failed" in result.output
