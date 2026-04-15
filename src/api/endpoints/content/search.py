# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Search API endpoints — knowledge graph and article similarity search."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from api.endpoints import _deps as deps
from api.middleware.auth import verify_api_key
from api.middleware.rate_limit import limiter
from api.schemas.response import APIResponse, success_response
from api.schemas.types import RoundedFloat
from core.llm import LLMClient
from core.observability import get_logger
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
    confidence: RoundedFloat
    search_type: str
    entities: list[str]
    sources: list[dict[str, Any]]
    metadata: dict[str, Any]


# ── Unified Search Endpoint ─────────────────────────────────────


@router.get("", response_model=APIResponse[SearchResponse])
@limiter.limit("100/minute")
async def search_unified(
    request: Request,
    q: str = Query(..., description="Search query"),
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
    local_engine: LocalSearchEngine = Depends(deps.Endpoints.get_local_engine),
    global_engine: GlobalSearchEngine = Depends(deps.Endpoints.get_global_engine),
    vector_repo: VectorRepo = Depends(deps.Endpoints.get_vector_repo),
    llm: LLMClient = Depends(deps.Endpoints.get_llm),
    hybrid_engine: HybridSearchEngine = Depends(deps.Endpoints.get_hybrid_engine),
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
    use_explicit_mode = explicit_mode in ("local", "global", "articles")

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
        elif explicit_mode == "articles":
            # Articles mode: direct vector search on articles
            engine_result = await _search_articles_direct(
                query=q,
                vector_repo=vector_repo,
                hybrid_engine=hybrid_engine,
                threshold=threshold,
                limit=limit,
                category=category,
                use_hybrid=use_hybrid,
            )
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

    # Note: Narrative synthesis and entity aggregation are planned features.
    # When EntityAggregator and NarrativeSynthesizer are implemented:
    # - If enrich_entities=True: aggregate entity neighborhoods
    # - If output_mode=NARRATIVE: synthesize narrative via LLM
    # Currently returns context mode behavior for both.

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


# ── Articles Direct Search Helper ─────────────────────────────────────


async def _search_articles_direct(
    query: str,
    vector_repo: VectorRepo,
    hybrid_engine: HybridSearchEngine | None,
    threshold: float = 0.0,
    limit: int = 20,
    category: str | None = None,
    use_hybrid: bool = True,
) -> dict[str, Any]:
    """Direct article search using vector similarity.

    Args:
        query: Search query.
        vector_repo: Vector repository for article embeddings.
        hybrid_engine: Optional hybrid search engine for BM25 + vector fusion.
        threshold: Similarity threshold for filtering.
        limit: Maximum results to return.
        category: Optional category filter.
        use_hybrid: Whether to use hybrid search (BM25 + vector).

    Returns:
        Dictionary with search results.

    """
    log = get_logger(__name__)

    try:
        if use_hybrid and hybrid_engine is not None:
            # Use hybrid search for better recall
            results = await hybrid_engine.search(
                query=query,
                limit=limit,
            )
            search_method = "hybrid"
        else:
            # Pure vector search
            results = await vector_repo.search_similar(
                query=query,
                limit=limit,
                threshold=threshold,
            )
            search_method = "vector"

        # Filter by category if specified (using metadata if available)
        if category and results:
            results = [r for r in results if getattr(r, "metadata", {}).get("category") == category]

        # Debug: Log actual score values
        if results:
            log.debug(
                "search_scores_debug",
                first_result_type=type(results[0]).__name__,
                first_score=getattr(results[0], "score", None),
                first_rrf_score=getattr(results[0], "rrf_score", None),
                first_metadata=getattr(results[0], "metadata", {}),
            )

        # Format results - handle HybridSearchResult dataclass
        sources = [
            {
                "id": getattr(r, "doc_id", ""),
                "title": getattr(r, "title", ""),
                "score": getattr(r, "score", 0.0),
                "summary": getattr(r, "content", "")[:200] if getattr(r, "content", "") else "",
            }
            for r in results
        ]

        # Extract entities from results metadata
        entities = []
        for r in results:
            meta = getattr(r, "metadata", {})
            if meta.get("entities"):
                entities.extend(meta["entities"])
        entities = list(set(entities))[:20]

        # Calculate confidence based on result quality
        if not results:
            confidence = 0.0
        else:
            avg_score = sum(getattr(r, "score", 0.0) for r in results) / len(results)
            confidence = min(1.0, avg_score * 2)  # Scale to 0-1

        log.info(
            "articles_direct_search",
            query=query[:50],
            results=len(results),
            method=search_method,
        )

        return {
            "answer": f"Found {len(results)} articles matching '{query}'.",
            "context_tokens": sum(len(getattr(r, "content", "")) // 4 for r in results),
            "confidence": confidence,
            "entities": entities,
            "sources": sources,
            "metadata": {
                "search_type": "articles",
                "search_method": search_method,
                "article_count": len(results),
                "threshold": threshold,
                "hybrid_used": use_hybrid and hybrid_engine is not None,
            },
        }

    except Exception as exc:
        log.error("articles_direct_search_failed", error=str(exc))
        return {
            "answer": f"Search failed: {exc!s}",
            "context_tokens": 0,
            "confidence": 0.0,
            "entities": [],
            "sources": [],
            "metadata": {"error": str(exc)},
        }


# ── DRIFT Search Endpoint ─────────────────────────────────────


class DriftSearchRequest(BaseModel):
    """Request model for DRIFT search."""

    query: str
    primer_k: int = 3
    max_follow_ups: int = 2
    confidence_threshold: RoundedFloat = 0.7


class DriftSearchResponse(BaseModel):
    """Response model for DRIFT search."""

    query: str
    answer: str
    confidence: RoundedFloat
    search_type: str = "drift"
    hierarchy: dict[str, Any]
    primer_communities: int
    follow_up_iterations: int
    total_llm_calls: int
    drift_mode: str
    metadata: dict[str, Any]


@router.post("/drift", response_model=APIResponse[DriftSearchResponse])
@limiter.limit("20/minute")
async def search_drift(
    request: Request,
    body: DriftSearchRequest,
    _: str = Depends(verify_api_key),
    local_engine: LocalSearchEngine = Depends(deps.Endpoints.get_local_engine),
    global_engine: GlobalSearchEngine = Depends(deps.Endpoints.get_global_engine),
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
        if "llm" in str(exc).lower():
            raise HTTPException(status_code=503, detail="LLM service unavailable")
        raise HTTPException(status_code=500, detail=f"DRIFT search failed: {exc}")


# ── MAGMA Memory Search Endpoints ─────────────────────────────────


class CausalSearchRequest(BaseModel):
    """Request model for causal search."""

    query: str
    """The causal reasoning query (e.g., 'Why did X happen?')."""

    max_depth: int = 3
    """Maximum depth for causal chain traversal."""

    min_confidence: RoundedFloat = 0.7
    """Minimum confidence for causal edges."""


class CausalSearchResponse(BaseModel):
    """Response model for causal search."""

    query: str
    answer: str
    causal_chain: list[dict[str, Any]]
    confidence: RoundedFloat
    metadata: dict[str, Any]


class TemporalSearchRequest(BaseModel):
    """Request model for temporal search."""

    query: str
    """The temporal reasoning query (e.g., 'When did X happen?')."""

    time_window_days: int = 7
    """Time window in days for temporal filtering."""

    limit: int = 10
    """Maximum number of events to return."""


class TemporalSearchResponse(BaseModel):
    """Response model for temporal search."""

    query: str
    events: list[dict[str, Any]]
    time_range: dict[str, Any]
    metadata: dict[str, Any]


@router.post("/causal", response_model=APIResponse[CausalSearchResponse])
@limiter.limit("10/minute")
async def search_causal(
    request: Request,
    body: CausalSearchRequest,
    _: str = Depends(verify_api_key),
    llm: LLMClient = Depends(deps.Endpoints.get_llm),
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
        llm: LLM client for embedding and intent classification.

    Returns:
        Causal chain with explanations and confidence scores.

    """
    from modules.memory.graphs.causal import CausalGraphRepo
    from modules.memory.retrieval.adaptive_search import AdaptiveSearchEngine

    log = get_logger(__name__)

    try:
        # Get dependencies
        graph_pool = deps.Endpoints.get_graph_pool()

        # Create repositories
        from modules.memory.graphs.temporal import TemporalGraphRepo

        temporal_repo = TemporalGraphRepo(pool=graph_pool)
        causal_repo = CausalGraphRepo(
            pool=graph_pool,
            confidence_threshold=body.min_confidence,
        )

        # Create real services for adaptive search
        class RealEmbeddingService:
            """Real embedding service using LLM client."""

            async def embed(self, text: str) -> list[float]:
                embeddings = await llm.embed_default([text])
                return embeddings[0] if embeddings and embeddings[0] else [0.0] * 384

        class RealIntentClassifier:
            """Real intent classifier using LLM."""

            async def classify(self, query: str):
                from modules.knowledge.search.intent.classifier import IntentClassifier

                classifier = IntentClassifier(llm=llm)
                return await classifier.classify(query)

        engine = AdaptiveSearchEngine(
            temporal_repo=temporal_repo,
            causal_repo=causal_repo,
            embedding_service=RealEmbeddingService(),
            intent_classifier=RealIntentClassifier(),
            max_depth=body.max_depth,
        )

        # Execute search
        results = await engine.search(
            query=body.query,
            intent=IntentType.WHY,
        )

        # Build causal chain from results
        causal_chain = [
            {
                "id": r["id"],
                "content": r.get("content", ""),
                "score": r.get("score", 0),
            }
            for r in results
        ]

        return success_response(
            CausalSearchResponse(
                query=body.query,
                answer=f"Found {len(causal_chain)} related events in causal chain.",
                causal_chain=causal_chain,
                confidence=sum(r.get("score", 0) for r in results) / max(len(results), 1),
                metadata={"depth": body.max_depth},
            )
        )

    except Exception as exc:
        log.error("causal_search_failed", error=str(exc))
        if "neo4j" in str(exc).lower():
            raise HTTPException(status_code=503, detail="Graph service unavailable")
        raise HTTPException(status_code=500, detail=f"Causal search failed: {exc}")


@router.post("/temporal", response_model=APIResponse[TemporalSearchResponse])
@limiter.limit("20/minute")
async def search_temporal(
    request: Request,
    body: TemporalSearchRequest,
    _: str = Depends(verify_api_key),
) -> APIResponse[TemporalSearchResponse]:
    """Temporal reasoning search using MAGMA multi-graph architecture.

    Retrieves events in chronological order to answer "When?" questions.

    Best for:
    - Timeline reconstruction
    - Event sequence analysis
    - Temporal pattern discovery

    Args:
        body: Temporal search request with query and parameters.
        _: Verified API key.

    Returns:
        Ordered list of events with temporal metadata.

    """
    from modules.memory.graphs.temporal import TemporalGraphRepo

    log = get_logger(__name__)

    try:
        # Get dependencies
        graph_pool = deps.Endpoints.get_graph_pool()

        # Create repository
        temporal_repo = TemporalGraphRepo(pool=graph_pool)

        # Get temporal chain
        events = await temporal_repo.get_temporal_chain(limit=body.limit)

        # Convert neo4j.time.DateTime to ISO string for JSON serialization
        for event in events:
            ts = event.get("timestamp")
            if ts is not None and hasattr(ts, "isoformat"):
                event["timestamp"] = ts.isoformat()

        # Build time range
        timestamps = [e.get("timestamp") for e in events if e.get("timestamp")]
        # Convert timestamps to strings for comparison
        time_range = {
            "start": min(timestamps) if timestamps else None,
            "end": max(timestamps) if timestamps else None,
            "window_days": body.time_window_days,
        }

        return success_response(
            TemporalSearchResponse(
                query=body.query,
                events=events,
                time_range=time_range,
                metadata={"limit": body.limit},
            )
        )

    except Exception as exc:
        log.error("temporal_search_failed", error=str(exc))
        if "neo4j" in str(exc).lower():
            raise HTTPException(status_code=503, detail="Graph service unavailable")
        raise HTTPException(status_code=500, detail=f"Temporal search failed: {exc}")
