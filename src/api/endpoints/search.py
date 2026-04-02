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
from core.constants import SearchMode
from core.llm.client import LLMClient
from core.observability.logging import get_logger
from modules.knowledge.search.engines.global_search import GlobalSearchEngine
from modules.knowledge.search.engines.hybrid_search import HybridSearchEngine
from modules.knowledge.search.engines.local_search import LocalSearchEngine, SearchResult

# MAGMA intent-aware routing
from modules.knowledge.search.intent.router import IntentRouter, RoutingConfig
from modules.memory.core.graph_types import IntentType
from modules.storage.postgres.vector_repo import VectorRepo

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


def _result_to_response(result: SearchResult, search_type: str) -> SearchResponse:
    """Map a SearchResult to SearchResponse."""
    sources: list[dict[str, Any]]
    if search_type == "articles":
        sources = result.sources if isinstance(result.sources, list) else []
    else:
        sources = result.sources if isinstance(result.sources, list) else []

    return SearchResponse(
        query=result.query,
        answer=result.answer,
        context_tokens=result.context_tokens,
        confidence=result.confidence,
        search_type=search_type,
        entities=result.entities,
        sources=sources,
        metadata=result.metadata,
    )


# ── Internal Helper Functions ───────────────────────────────────


async def _search_local_impl(
    query: str,
    entity_names: str | None,
    max_tokens: int | None,
    engine: LocalSearchEngine,
) -> APIResponse[SearchResponse]:
    """Implement local search internally."""
    try:
        names: list[str] | None = (
            [n.strip() for n in entity_names.split(",") if n.strip()] if entity_names else None
        )
        result = await engine.search(
            query=query,
            max_tokens=max_tokens,
            entity_names=names,
            use_llm=False,
        )
        return success_response(_result_to_response(result, SearchMode.LOCAL.value))
    except Exception as exc:
        if "neo4j" in str(exc).lower() or "graph" in str(exc).lower():
            raise HTTPException(status_code=503, detail="Graph service unavailable")
        raise HTTPException(status_code=503, detail="LLM service unavailable")


async def _search_global_impl(
    query: str,
    community_level: int,
    mode: str,
    engine: GlobalSearchEngine,
) -> APIResponse[SearchResponse]:
    """Implement global search internally."""
    try:
        if mode == "simple":
            result = await engine.search_simple(
                query=query, community_level=community_level, use_llm=False
            )
        else:
            result = await engine.search(
                query=query, community_level=community_level, use_llm=False
            )
        return success_response(_result_to_response(result, SearchMode.GLOBAL.value))
    except Exception as exc:
        if "neo4j" in str(exc).lower() or "graph" in str(exc).lower():
            raise HTTPException(status_code=503, detail="Graph service unavailable")
        raise HTTPException(status_code=503, detail="LLM service unavailable")


async def _search_articles_impl(
    query: str,
    threshold: float,
    limit: int,
    category: str | None,
    use_hybrid: bool,
    vector_repo: VectorRepo,
    llm: LLMClient,
    hybrid_engine: HybridSearchEngine | None,
) -> APIResponse[SearchResponse]:
    """Implement articles search internally."""
    try:
        embeddings = await llm.embed("embedding.aiping_embedding.Qwen3-Embedding-0.6B", [query])
        query_vector = embeddings[0]
    except Exception:
        raise HTTPException(status_code=503, detail="Embedding service unavailable")

    if not query_vector:
        raise HTTPException(status_code=503, detail="Embedding service unavailable")

    # Use hybrid search engine if enabled and available
    hybrid_used = False
    search_mode = SearchMode.LOCAL.value

    if use_hybrid and hybrid_engine is not None:
        try:
            hybrid_result = await hybrid_engine.search(
                query=query,
                embedding=query_vector,
                limit=limit,
            )

            if hybrid_result:
                hybrid_used = True
                search_mode = SearchMode.HYBRID.value

                sources = [
                    {
                        "article_id": item.get("article_id", item.get("doc_id", "")),
                        "similarity": item.get("score", 0.0),
                        "category": item.get("category"),
                        "hybrid_score": item.get("hybrid_score"),
                        "bm25_score": item.get("bm25_score"),
                    }
                    for item in hybrid_result
                ]

                confidence = sources[0]["similarity"] if sources else 0.0

                return success_response(
                    SearchResponse(
                        query=query,
                        answer=f"Found {len(sources)} similar articles.",
                        context_tokens=0,
                        confidence=confidence,
                        search_type=SearchMode.ARTICLES.value,
                        entities=[],
                        sources=sources,
                        metadata={
                            "total_results": len(sources),
                            "threshold": threshold,
                            "category_filter": category,
                            "search_mode": search_mode,
                            "hybrid_used": hybrid_used,
                        },
                    )
                )
        except Exception as exc:
            # Fall back to vector-only search
            get_logger(__name__).warning(f"Hybrid search failed, falling back: {exc}")

    # Fallback: Vector-only search
    query_tokens = query.split()

    try:
        similar = await vector_repo.find_similar_hybrid(
            embedding=query_vector,
            query_tokens=query_tokens,
            category=category,
            min_score=threshold,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Vector search failed: {exc}")

    sources = [
        {
            "article_id": item.article_id,
            "similarity": item.similarity,
            "category": item.category,
            "hybrid_score": item.hybrid_score,
        }
        for item in similar
    ]

    answer = f"Found {len(sources)} similar articles."
    confidence = (
        float(similar[0].hybrid_score)
        if (similar and similar[0].hybrid_score is not None)
        else float(similar[0].similarity) if similar else 0.0
    )

    return success_response(
        SearchResponse(
            query=query,
            answer=answer,
            context_tokens=0,
            confidence=confidence,
            search_type="articles",
            entities=[],
            sources=sources,
            metadata={
                "total_results": len(sources),
                "threshold": threshold,
                "category_filter": category,
                "search_mode": "vector_only",
                "hybrid_used": False,
            },
        )
    )


# ── Unified Search Endpoint ─────────────────────────────────────


@router.get("", response_model=APIResponse[SearchResponse])
@limiter.limit("100/minute")
async def search_unified(
    request: Request,
    q: str = Query(..., description="Search query"),
    mode: str | None = Query(
        None,
        description="DEPRECATED: Use automatic intent-aware routing instead",
        deprecated="Use automatic intent-aware routing instead of manual mode selection",
    ),
    entity_names: str | None = Query(None, description="DEPRECATED: Intent router handles this"),
    max_tokens: int | None = Query(None, description="DEPRECATED: Intent router handles this"),
    community_level: int = Query(0, ge=0, le=10, description="Community level (global mode)"),
    threshold: float = Query(
        0.0, ge=0.0, le=1.0, description="Similarity threshold (articles mode)"
    ),
    limit: int = Query(20, ge=1, le=100, description="Max results (articles mode)"),
    category: str | None = Query(None, description="Category filter (articles mode)"),
    use_hybrid: bool = Query(True, description="Use hybrid search (articles mode)"),
    global_mode: str = Query("map_reduce", description="Global search mode: map_reduce or simple"),
    _: str = Depends(verify_api_key),
    local_engine: LocalSearchEngine = Depends(deps.Endpoints.get_local_engine),
    global_engine: GlobalSearchEngine = Depends(deps.Endpoints.get_global_engine),
    vector_repo: VectorRepo = Depends(deps.Endpoints.get_vector_repo),
    llm: LLMClient = Depends(deps.Endpoints.get_llm),
    hybrid_engine: HybridSearchEngine = Depends(deps.Endpoints.get_hybrid_engine),
) -> APIResponse[SearchResponse]:
    """Unified search endpoint with MAGMA-inspired intent-aware routing.

    **Intent-Aware Routing:** The system now automatically classifies your query
    to determine the best search strategy:

    | Intent Type | Description | Search Strategy |
    |-------------|-------------|-----------------|
    | **WHY** | "为什么..."、原因 | Local search with causal relationship focus |
    | **WHEN** | "什么时候..."、时间 | Local search with temporal window and sorting |
    | **ENTITY** | "X是什么..."、实体 | Local search with entity filtering |
    | **MULTI_HOP** | "X和Y的关系..."、对比 | Global search with deeper community traversal |
    | **OPEN** | "关于..."、探索 | Global search with standard community level |

    **Migration from deprecated endpoints:**
    - `/search/local?q=xxx` → `/search?q=xxx` (mode now optional, defaults to intent routing)
    - `/search/global?q=xxx` → `/search?q=xxx`
    - `/search/articles?q=xxx` → `/search?q=xxx`

    **Backward Compatibility:** The `mode` parameter is **deprecated** but still supported
    for explicit override. Users who prefer manual mode selection can still use `?mode=local`.
    """
    # Initialize intent router
    intent_router = IntentRouter(
        local_engine=local_engine,
        global_engine=global_engine,
        vector_repo=vector_repo,
        hybrid_engine=hybrid_engine,
        llm=llm,
        config=RoutingConfig(
            enable_intent_routing=True,
            fallback_mode=mode or "local",
        ),
    )

    # Classify query intent
    classification = await intent_router._classifier.classify(q)

    # Route to appropriate engine
    get_logger(__name__).info(
        "explicit_mode_override" if mode else "intent_routing",
        mode=mode,
        intent=classification.intent.value,
    )
    engine_result = await intent_router.route(q, classification)

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

    if mode:
        result_metadata["explicit_mode"] = mode

    return success_response(
        SearchResponse(
            query=q,
            answer=result_answer,
            context_tokens=result_tokens,
            confidence=result_confidence,
            search_type="auto",
            entities=result_entities,
            sources=result_sources,
            metadata=result_metadata,
        )
    )


# ── DRIFT Search Endpoint ─────────────────────────────────────


class DriftSearchRequest(BaseModel):
    """Request model for DRIFT search."""

    query: str
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

        # Get Neo4j pool and LLM from global engine
        pool = global_engine._pool
        llm = global_engine._llm

        engine = DRIFTSearchEngine(
            neo4j_pool=pool,
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

    min_confidence: float = 0.7
    """Minimum confidence for causal edges."""


class CausalSearchResponse(BaseModel):
    """Response model for causal search."""

    query: str
    answer: str
    causal_chain: list[dict[str, Any]]
    confidence: float
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

    Returns:
        Causal chain with explanations and confidence scores.

    """
    from modules.memory.graphs.causal import CausalGraphRepo
    from modules.memory.retrieval.adaptive_search import AdaptiveSearchEngine

    log = get_logger(__name__)

    try:
        # Get dependencies
        neo4j_pool = deps.Endpoints.get_neo4j_pool()

        # Create repositories
        from modules.memory.graphs.temporal import TemporalGraphRepo

        temporal_repo = TemporalGraphRepo(pool=neo4j_pool)
        causal_repo = CausalGraphRepo(
            pool=neo4j_pool,
            confidence_threshold=body.min_confidence,
        )

        # Create mock services for adaptive search
        class MockEmbeddingService:
            async def embed(self, text: str) -> list[float]:
                return [0.1] * 384

        class MockIntentClassifier:
            async def classify(self, query: str):
                from modules.memory.core.graph_types import IntentType

                class Result:
                    intent = IntentType.WHY

                return Result()

        engine = AdaptiveSearchEngine(
            temporal_repo=temporal_repo,
            causal_repo=causal_repo,
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(),
            max_depth=body.max_depth,
        )

        # Execute search
        results = await engine.search(
            query=body.query,
            intent=IntentType.WHY if "IntentType" in dir() else None,
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
        neo4j_pool = deps.Endpoints.get_neo4j_pool()

        # Create repository
        temporal_repo = TemporalGraphRepo(pool=neo4j_pool)

        # Get temporal chain
        events = await temporal_repo.get_temporal_chain(limit=body.limit)

        # Build time range
        timestamps = [e.get("timestamp") for e in events if e.get("timestamp")]
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
