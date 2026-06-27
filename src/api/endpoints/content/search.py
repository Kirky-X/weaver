# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Search API endpoints — knowledge graph and article similarity search."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.dependencies import (
    get_embedding_service_optional,
    get_global_search_engine,
    get_graph_pool,
    get_hybrid_engine,
    get_intent_classifier_optional,
    get_llm_client,
    get_local_search_engine,
    get_vector_repo,
)
from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from core.llm import LLMClient
from core.observability import get_logger
from core.protocols import GraphPool
from modules.knowledge.search import (
    GlobalSearchEngine,
    HybridSearchEngine,
    IntentClassification,
    IntentRouter,
    LocalSearchEngine,
    QueryIntent,
    RoutingConfig,
)
from modules.memory import IntentType, OutputMode
from modules.storage import VectorRepo

router = APIRouter(prefix="/search", tags=["search"])


# ── Request/Response Models ─────────────────────────────────────


class SearchResponse(BaseModel):
    """Unified response model for all search endpoints."""

    query: str
    answer: str
    context_tokens: int
    confidence: float
    search_type: str
    entities: list[str]
    sources: list[dict[str, Any]]
    metadata: dict[str, Any]


# ── Unified Search Endpoint ─────────────────────────────────────


@router.get("", response_model=APIResponse[SearchResponse])
async def search_unified(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
    mode: str | None = Query(
        None,
        description="Explicit search mode: 'local' for vector search, 'global' for community search, 'auto' for intent-based routing (default)",
    ),
    community_level: int = Query(0, ge=0, le=10, description="Community level (global mode)"),
    threshold: float = Query(
        0.0, ge=0.0, le=1.0, description="Similarity threshold (articles mode)"
    ),
    limit: int = Query(20, ge=1, le=100, description="Max results (articles mode)"),
    category: str | None = Query(None, description="Category filter (articles mode)"),
    use_hybrid: bool = Query(True, description="Use hybrid search (articles mode)"),
    global_mode: str = Query("map_reduce", description="Global search mode: map_reduce or simple"),
    output_mode: str | None = Query(
        None,
        description="Output format: 'context' for raw snippets, 'narrative' for LLM-synthesized answer",
    ),
    enrich_entities: bool | None = Query(
        None,
        description="Enable entity aggregation to enrich results with entity neighborhoods",
    ),
    _: str = Depends(verify_api_key),
    local_engine: LocalSearchEngine = Depends(get_local_search_engine),
    global_engine: GlobalSearchEngine = Depends(get_global_search_engine),
    vector_repo: VectorRepo = Depends(get_vector_repo),
    llm: LLMClient = Depends(get_llm_client),
    hybrid_engine: HybridSearchEngine = Depends(get_hybrid_engine),
) -> APIResponse[SearchResponse]:
    """Unified search endpoint with MAGMA-inspired intent-aware routing.

    **Search Modes:**
    - `mode=local`: Direct vector search for entity neighborhoods
    - `mode=global`: Community-level search for broader context
    - `mode=auto` (default): Intent-based automatic routing

    **Intent-Aware Routing (when mode=auto):**
    The system automatically classifies your query to determine the best search strategy:

    | Intent Type | Description | Search Strategy |
    |-------------|-------------|-----------------|
    | **WHY** | "为什么..."、原因 | Local search with causal relationship focus |
    | **WHEN** | "什么时候..."、时间 | Local search with temporal window and sorting |
    | **ENTITY** | "X是什么..."、实体 | Local search with entity filtering |
    | **MULTI_HOP** | "X和Y的关系..."、对比 | Global search with deeper community traversal |
    | **OPEN** | "关于..."、探索 | Global search with standard community level |
    """
    # Validate output_mode (default to CONTEXT)
    out_mode_value = output_mode if isinstance(output_mode, str) else "context"
    try:
        out_mode = OutputMode(out_mode_value.upper())
    except ValueError:
        out_mode = OutputMode.CONTEXT

    # Validate enrich_entities (default to False)
    enrich = enrich_entities if isinstance(enrich_entities, bool) else False

    # Determine search mode
    explicit_mode = mode.lower() if mode and isinstance(mode, str) else None
    use_explicit_mode = explicit_mode in ("local", "global")

    # Initialize intent router for automatic routing (when not using explicit mode)
    intent_router = IntentRouter(
        local_engine=local_engine,
        global_engine=global_engine,
        vector_repo=vector_repo,
        hybrid_engine=hybrid_engine,
        llm=llm,
        config=RoutingConfig(
            enable_intent_routing=not use_explicit_mode,
            fallback_mode="local",
        ),
    )

    # Get result based on mode
    if use_explicit_mode:
        # Explicit mode: bypass intent routing, call engines directly
        if explicit_mode == "local":
            engine_result = await local_engine.search(q)
        else:  # global
            engine_result = await global_engine.search(q, community_level=community_level)
        classification = IntentClassification(
            intent=QueryIntent.OPEN,
            confidence=1.0,
        )
    else:
        # Auto mode: use intent routing
        classification = await intent_router._classifier.classify(q)
        engine_result = await intent_router.route(q, classification)
    get_logger(__name__).info(
        "intent_routing",
        intent=classification.intent.value,
        output_mode=out_mode.value,
        enrich_entities=enrich,
    )

    # Handle both dict and SearchResult object returns
    if isinstance(engine_result, dict):
        result_answer = engine_result.get("answer", "")
        result_tokens = engine_result.get("context_tokens", 0)
        result_confidence = engine_result.get("confidence", 0.0)
        result_entities = engine_result.get("entities", [])
        result_sources = engine_result.get("sources", [])
        result_metadata = engine_result.get("metadata", {})
    else:
        result_answer = engine_result.answer
        result_tokens = engine_result.context_tokens
        result_confidence = engine_result.confidence
        result_entities = engine_result.entities
        result_sources = engine_result.sources if isinstance(engine_result.sources, list) else []
        result_metadata = engine_result.metadata

    result_metadata["output_mode"] = out_mode.value
    result_metadata["enrich_entities"] = enrich
    result_metadata["intent"] = classification.intent.value
    result_metadata["intent_confidence"] = classification.confidence

    # Determine search_type for response
    search_type = explicit_mode if use_explicit_mode else "auto"

    # Note: Narrative synthesis and entity aggregation are handled by MAGMA
    # memory integration when output_mode=NARRATIVE or enrich_entities=True.

    return success_response(
        SearchResponse(
            query=q,
            answer=result_answer,
            context_tokens=result_tokens,
            confidence=result_confidence,
            search_type=search_type,
            entities=result_entities,
            sources=result_sources,
            metadata=result_metadata,
        )
    )


# ── DRIFT Search Endpoint ─────────────────────────────────────


class DriftSearchRequest(BaseModel):
    """Request model for DRIFT search."""

    query: str = Field(..., min_length=1, description="Search query (non-empty)")
    primer_k: int = 3
    max_follow_ups: int = 2
    confidence_threshold: float = 0.7


class DriftSearchResponse(BaseModel):
    """Response model for DRIFT search."""

    query: str
    answer: str
    confidence: float
    search_type: str = "drift"
    hierarchy: dict[str, Any]
    primer_communities: int
    follow_up_iterations: int
    total_llm_calls: int
    drift_mode: str
    metadata: dict[str, Any]


@router.post("/drift", response_model=APIResponse[DriftSearchResponse])
async def search_drift(
    request: Request,
    body: DriftSearchRequest,
    _: str = Depends(verify_api_key),
    local_engine: LocalSearchEngine = Depends(get_local_search_engine),
    global_engine: GlobalSearchEngine = Depends(get_global_search_engine),
) -> APIResponse[DriftSearchResponse]:
    """DRIFT Search - Dynamic Reasoning and Inference Framework.

    Combines global community insights with local entity details through
    a three-phase iterative search process:

    1. Primer Phase: Vector search community reports, generate initial answer
    2. Follow-Up Phase: Iterative local search based on generated questions
    3. Output Phase: Aggregate into hierarchical response

    Best for:
    - Complex multi-faceted queries
    - Research-style exploration
    - Questions requiring both breadth and depth

    Args:
        body: DRIFT search request with query and optional parameters.
        _: Verified API key.
        local_engine: Local search engine for follow-up phase.
        global_engine: Global search engine dependency (for pool access).

    Returns:
        Hierarchical search result with primer and follow-up answers.

    """
    from modules.knowledge.search.engines.drift_search import DriftConfig, DRIFTSearchEngine

    try:
        config = DriftConfig(
            primer_k=body.primer_k,
            max_follow_ups=body.max_follow_ups,
            confidence_threshold=body.confidence_threshold,
        )

        # Get context builder and LLM from global engine
        context_builder = global_engine._context_builder
        llm = global_engine._llm

        engine = DRIFTSearchEngine(
            context_builder=context_builder,
            llm=llm,
            config=config,
            local_engine=local_engine,
        )

        result = await engine.search(body.query)

        return success_response(
            DriftSearchResponse(
                query=result.query,
                answer=result.answer,
                confidence=result.confidence,
                search_type="drift",
                hierarchy={
                    "primer": result.hierarchy.primer,
                    "follow_ups": result.hierarchy.follow_ups,
                },
                primer_communities=result.primer_communities,
                follow_up_iterations=result.follow_up_iterations,
                total_llm_calls=result.total_llm_calls,
                drift_mode=result.drift_mode,
                metadata=result.metadata,
            )
        )

    except Exception as exc:
        get_logger(__name__).error("drift_search_failed", error=str(exc))
        if "neo4j" in str(exc).lower() or "graph" in str(exc).lower():
            raise HTTPException(status_code=503, detail="Graph service unavailable")
        if "llm" in str(exc).lower() or "circuit breaker" in str(exc).lower():
            raise HTTPException(status_code=503, detail="LLM service unavailable")
        raise HTTPException(status_code=500, detail=f"DRIFT search failed: {exc}")


# ── MAGMA Memory Search Endpoints ─────────────────────────────────


class CausalSearchRequest(BaseModel):
    """Request model for causal search."""

    query: str = Field(
        ..., min_length=1, description="The causal reasoning query (e.g., 'Why did X happen?')"
    )

    max_depth: int = Field(default=3, ge=1, le=10)
    """Maximum depth for causal chain traversal."""

    min_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    """Minimum confidence for causal edges."""


class CausalChainItem(BaseModel):
    """Single item in a causal chain."""

    id: str
    content: str
    score: float


class CausalSearchResponse(BaseModel):
    """Response model for causal search."""

    query: str
    answer: str
    causal_chain: list[CausalChainItem]
    confidence: float
    metadata: dict[str, Any]


class TemporalSearchRequest(BaseModel):
    """Request model for temporal search."""

    query: str = Field(
        ..., min_length=1, description="The temporal reasoning query (e.g., 'When did X happen?')"
    )

    time_range: str = "7d"
    """Time range for temporal filtering. Format: '<N><unit>' where unit is d/h/m (e.g., '7d', '24h', '30m')."""

    limit: int = 10
    """Maximum number of events to return."""


class TemporalSearchResponse(BaseModel):
    """Response model for temporal search."""

    query: str
    events: list[dict[str, Any]]
    time_range: dict[str, Any]
    metadata: dict[str, Any]


@router.post("/causal", response_model=APIResponse[CausalSearchResponse])
async def search_causal(
    request: Request,
    body: CausalSearchRequest,
    _: str = Depends(verify_api_key),
    graph_pool: GraphPool = Depends(get_graph_pool),
    embedding_service: Any | None = Depends(get_embedding_service_optional),
    intent_classifier: Any | None = Depends(get_intent_classifier_optional),
) -> APIResponse[CausalSearchResponse]:
    """Causal reasoning search using MAGMA multi-graph architecture.

    Traverses causal chains to answer "Why?" questions.

    Best for:
    - Understanding cause-effect relationships
    - Explaining why events occurred
    - Analyzing event cascades

    Args:
        body: Causal search request with query and parameters.
        _: Verified API key.
        graph_pool: Graph database pool.
        embedding_service: Embedding service (optional, degrades gracefully).
        intent_classifier: Intent classifier (optional, degrades gracefully).

    Returns:
        Causal chain with explanations and confidence scores.

    """
    from modules.memory.graphs.causal import CausalGraphRepo
    from modules.memory.retrieval.adaptive_search import AdaptiveSearchEngine

    log = get_logger(__name__)

    try:
        # Create repositories
        from modules.memory.graphs.temporal import TemporalGraphRepo

        temporal_repo = TemporalGraphRepo(pool=graph_pool)
        causal_repo = CausalGraphRepo(
            pool=graph_pool,
            confidence_threshold=body.min_confidence,
        )

        # Semantic search requires embedding service — zero-vector fallback is NOT acceptable
        # (zero vectors make all texts "equivalent", breaking semantic similarity entirely)
        if embedding_service is None:
            log.warning("causal_search_embedding_unavailable", query=body.query[:50])
            raise HTTPException(
                status_code=503, detail="Embedding service unavailable for causal search"
            )
        if intent_classifier is None:
            log.warning("causal_search_intent_classifier_unavailable", query=body.query[:50])
            raise HTTPException(
                status_code=503, detail="Intent classifier unavailable for causal search"
            )

        engine = AdaptiveSearchEngine(
            temporal_repo=temporal_repo,
            causal_repo=causal_repo,
            embedding_service=embedding_service,
            intent_classifier=intent_classifier,
            max_depth=body.max_depth,
        )

        # Execute search (with timeout protection)
        results = await asyncio.wait_for(
            engine.search(query=body.query, intent=IntentType.WHY),
            timeout=60.0,
        )

        # D5 / Task 5.1: pull traversal metadata from engine.last_metadata
        # (populated by _beam_search → _prefetch_neighbors via Task 3.5).
        # causal_edges_traversed counts neighbors reached via CAUSES/ENABLES
        # edges (0 when graph DB has no CAUSAL edges — Q1 finding).
        # degraded is set when score_range == 0 with >=2 results (D3 fix).
        engine_metadata = engine.last_metadata
        causal_edges_traversed = int(engine_metadata.get("causal_edges_traversed", 0))
        degraded = bool(engine_metadata.get("degraded", False))

        # Build causal chain from results
        causal_chain = [
            CausalChainItem(
                id=r["id"],
                content=r.get("content", ""),
                score=r.get("score", 0),
            )
            for r in results
        ]

        # D5 / Task 5.2-5.4: answer text reflects actual traversal path,
        # NOT a hardcoded "found N causal chains" lie. Three branches:
        # - causal_edges_traversed > 0: real causal chain traversal
        # - == 0 and results non-empty: only semantic anchors, no causal edge
        # - empty results: no anchors at all
        if not causal_chain:
            answer = "未找到与查询相关的事件"
            confidence = 0.0
        elif causal_edges_traversed > 0:
            answer = f"找到 {len(causal_chain)} 个事件的因果链（深度 {body.max_depth}）"
            confidence = sum(r.get("score", 0) for r in results) / max(len(results), 1)
        else:
            answer = f"未找到与查询相关的因果链，返回 {len(causal_chain)} 个语义相关事件"
            confidence = sum(r.get("score", 0) for r in results) / max(len(results), 1)

        # D3 / Task 5.5: when scoring function degraded (all scores identical),
        # cap confidence at 0.3 to distinguish "no real differentiation" from
        # "high-confidence result". This prevents confidence=1.0 lies when
        # every anchor has the same exp(2.0)=7.389 raw score (the bug).
        if degraded:
            confidence = min(confidence, 0.3)

        return success_response(
            CausalSearchResponse(
                query=body.query,
                answer=answer,
                causal_chain=causal_chain,
                confidence=confidence,
                # Task 5.6: expose causal_edges_traversed + degraded for callers
                metadata={
                    "depth": body.max_depth,
                    "causal_edges_traversed": causal_edges_traversed,
                    "degraded": degraded,
                },
            )
        )

    except TimeoutError:
        log.error("causal_search_timeout", query=body.query)
        raise HTTPException(status_code=504, detail="Causal search timed out")
    except HTTPException:
        raise
    except Exception as exc:
        log.error("causal_search_failed", error=str(exc))
        if "neo4j" in str(exc).lower():
            raise HTTPException(status_code=503, detail="Graph service unavailable")
        raise HTTPException(
            status_code=500, detail=f"Internal server error during causal search: {exc}"
        )


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


_TIME_RANGE_RE = re.compile(r"^(\d+)([dhm])$")


def _parse_time_range(time_range: str) -> tuple[int, int]:
    """Parse time range string like '7d', '24h', '30m' to (start, end) timestamps.

    Args:
        time_range: Time range string (e.g., "7d", "24h", "30m").

    Returns:
        Tuple of (start_time, end_time) as INT64 seconds since epoch.
        end_time is current time; start_time is end_time minus the parsed window.

    Raises:
        HTTPException: If format is invalid (status 400).

    """
    match = _TIME_RANGE_RE.match(time_range.strip().lower())
    if not match:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid time_range format: '{time_range}'. "
                "Expected format: '<N><unit>' where unit is d/h/m (e.g., '7d', '24h', '30m')."
            ),
        )

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "d":
        seconds = value * 86400
    elif unit == "h":
        seconds = value * 3600
    else:  # "m"
        seconds = value * 60

    end_time = int(time.time())
    start_time = end_time - seconds
    return start_time, end_time


def _is_valid_event_timestamp(ts: Any) -> bool:
    """Check if event timestamp is valid (not legacy dirty data).

    LadybugDB event_time is INT64 — dirty data has value 0 (from writer bug).
    Neo4j timestamp is datetime — always valid if not None.

    Returns:
        True if timestamp is valid, False if dirty (0) or missing.

    """
    if isinstance(ts, (int, float)):
        return ts > 0
    return ts is not None


async def _semantic_temporal_search(
    temporal_repo: Any,
    query: str,
    limit: int,
    embedding_service: Any,
    start_time: int,
    end_time: int,
) -> list[dict[str, Any]]:
    """Semantic search over temporal events using embedding similarity.

    Fetches events via get_events_by_timerange (time-window filtered),
    computes content embeddings, and ranks by cosine similarity to the query embedding.
    """
    query_embedding = await embedding_service.embed(query)

    all_events = await asyncio.wait_for(
        temporal_repo.get_events_by_timerange(start_time=start_time, end_time=end_time, limit=500),
        timeout=30.0,
    )

    # Filter out legacy dirty data (event_time=0 from writer bug)
    all_events = [e for e in all_events if _is_valid_event_timestamp(e.get("timestamp"))]

    if not all_events:
        return []

    contents = [e.get("content", "") for e in all_events]
    event_embeddings = await embedding_service.embed_batch(contents)

    scored: list[tuple[float, dict[str, Any]]] = []
    for event, emb in zip(all_events, event_embeddings, strict=True):
        sim = _cosine_similarity(query_embedding, emb)
        attr = event.get("attributes")
        if isinstance(attr, str):
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                event["attributes"] = json.loads(attr)
        event["similarity_score"] = round(sim, 4)
        scored.append((sim, event))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:limit]]


@router.post("/temporal", response_model=APIResponse[TemporalSearchResponse])
async def search_temporal(
    request: Request,
    body: TemporalSearchRequest,
    _: str = Depends(verify_api_key),
    graph_pool: GraphPool = Depends(get_graph_pool),
    embedding_service: Any | None = Depends(get_embedding_service_optional),
) -> APIResponse[TemporalSearchResponse]:
    """Temporal reasoning search using MAGMA multi-graph architecture.

    Retrieves events in chronological order to answer "When?" questions.

    When embedding service is available, uses semantic similarity ranking.
    Otherwise, falls back to CONTAINS substring matching.

    Best for:
    - Timeline reconstruction
    - Event sequence analysis
    - Temporal pattern discovery

    Args:
        body: Temporal search request with query and parameters.
        _: Verified API key.
        graph_pool: Graph database pool.
        embedding_service: Optional embedding service for semantic ranking.

    Returns:
        Ordered list of events with temporal metadata.

    """
    from modules.memory.graphs.temporal import TemporalGraphRepo

    log = get_logger(__name__)

    try:
        # Parse time range string (e.g., "7d", "24h", "30m") to (start, end) timestamps
        start_time, end_time = _parse_time_range(body.time_range)

        # Create repository
        temporal_repo = TemporalGraphRepo(pool=graph_pool)

        # Semantic search when embedding service is available;
        # otherwise CONTAINS substring matching only (may return empty)
        if embedding_service is not None and embedding_service.is_ready():
            try:
                events = await _semantic_temporal_search(
                    temporal_repo=temporal_repo,
                    query=body.query,
                    limit=body.limit,
                    embedding_service=embedding_service,
                    start_time=start_time,
                    end_time=end_time,
                )
            except Exception as emb_exc:
                # Embedding batch timeout/failure → fall back to substring search
                # (P0-2: previously returned 500; now degrades gracefully)
                log.warning(
                    "temporal_search_embedding_fallback",
                    error=str(emb_exc),
                    query=body.query[:50],
                )
                events = await asyncio.wait_for(
                    temporal_repo.search_temporal_events(
                        query=body.query,
                        limit=body.limit,
                        start_time=start_time,
                        end_time=end_time,
                    ),
                    timeout=30.0,
                )
        else:
            events = await asyncio.wait_for(
                temporal_repo.search_temporal_events(
                    query=body.query,
                    limit=body.limit,
                    start_time=start_time,
                    end_time=end_time,
                ),
                timeout=30.0,
            )

        # Force filter: exclude legacy dirty data (timestamp=0 from writer bug)
        events = [e for e in events if _is_valid_event_timestamp(e.get("timestamp"))]

        # Convert neo4j.time.DateTime to ISO string for JSON serialization
        for event in events:
            ts = event.get("timestamp")
            if ts is not None and hasattr(ts, "isoformat"):
                event["timestamp"] = ts.isoformat()

        # Build time range (request window, not event min/max)
        window_days = (end_time - start_time) / 86400.0
        time_range = {
            "start": start_time,
            "end": end_time,
            "window_days": window_days,
        }

        return success_response(
            TemporalSearchResponse(
                query=body.query,
                events=events,
                time_range=time_range,
                metadata={"limit": body.limit},
            )
        )

    except TimeoutError:
        log.error("temporal_search_timeout", limit=body.limit)
        raise HTTPException(status_code=504, detail="Temporal search timed out")
    except HTTPException:
        raise
    except Exception as exc:
        log.error("temporal_search_failed", error=str(exc))
        if "neo4j" in str(exc).lower():
            raise HTTPException(status_code=503, detail="Graph service unavailable")
        raise HTTPException(
            status_code=500, detail=f"Internal server error during temporal search: {exc}"
        )
