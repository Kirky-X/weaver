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
from core.llm.client import LLMClient
from modules.search.engines.global_search import GlobalSearchEngine
from modules.search.engines.local_search import LocalSearchEngine, SearchResult
from modules.storage.vector_repo import VectorRepo

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


# ── Endpoints ───────────────────────────────────────────────────


@router.get("/local", response_model=APIResponse[SearchResponse])
@limiter.limit("100/minute")
async def search_local(
    request: Request,
    q: str = Query(..., description="Search query"),
    entity_names: str | None = Query(None, description="Comma-separated entity names to focus on"),
    max_tokens: int | None = Query(None, description="Max context tokens"),
    _: str = Depends(verify_api_key),
    engine: LocalSearchEngine = Depends(deps.Endpoints.get_local_engine),
) -> APIResponse[SearchResponse]:
    """Entity-focused knowledge graph Q&A.

    Best for: "Who is X?", "How are X and Y related?", specific entity queries.
    """
    try:
        names: list[str] | None = (
            [n.strip() for n in entity_names.split(",") if n.strip()] if entity_names else None
        )
        result = await engine.search(
            query=q,
            max_tokens=max_tokens,
            entity_names=names,
            use_llm=False,
        )
        return success_response(_result_to_response(result, "local"))
    except Exception as exc:
        if "neo4j" in str(exc).lower() or "graph" in str(exc).lower():
            raise HTTPException(status_code=503, detail="Graph service unavailable")
        raise HTTPException(status_code=503, detail="LLM service unavailable")


@router.get("/global", response_model=APIResponse[SearchResponse])
@limiter.limit("100/minute")
async def search_global(
    request: Request,
    q: str = Query(..., description="Search query"),
    community_level: int = Query(0, ge=0, le=10, description="Community hierarchy level"),
    mode: str = Query("map_reduce", description="Search mode: map_reduce or simple"),
    _: str = Depends(verify_api_key),
    engine: GlobalSearchEngine = Depends(deps.Endpoints.get_global_engine),
) -> APIResponse[SearchResponse]:
    """Community-level aggregated search (Map-Reduce pattern).

    Best for: broad exploratory queries spanning multiple topics.
    """
    try:
        if mode == "simple":
            result = await engine.search_simple(
                query=q, community_level=community_level, use_llm=False
            )
        else:
            result = await engine.search(query=q, community_level=community_level, use_llm=False)
        return success_response(_result_to_response(result, "global"))
    except Exception as exc:
        if "neo4j" in str(exc).lower() or "graph" in str(exc).lower():
            raise HTTPException(status_code=503, detail="Graph service unavailable")
        raise HTTPException(status_code=503, detail="LLM service unavailable")


@router.get("/articles", response_model=APIResponse[SearchResponse])
@limiter.limit("100/minute")
async def search_articles(
    request: Request,
    q: str = Query(..., description="Search query text"),
    threshold: float = Query(0.0, ge=0.0, le=1.0, description="Min similarity threshold"),
    limit: int = Query(20, ge=1, le=100, description="Max results to return"),
    category: str | None = Query(None, description="Filter by article category"),
    _: str = Depends(verify_api_key),
    vector_repo: VectorRepo = Depends(deps.Endpoints.get_vector_repo),
    llm: LLMClient = Depends(deps.Endpoints.get_llm),
) -> APIResponse[SearchResponse]:
    """Find similar articles using hybrid vector + keyword scoring."""
    try:
        embeddings = await llm.batch_embed([q])
        query_vector = embeddings[0]
    except Exception:
        raise HTTPException(status_code=503, detail="Embedding service unavailable")

    if not query_vector:
        raise HTTPException(status_code=503, detail="Embedding service unavailable")

    query_tokens = q.split()

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
            query=q,
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
            },
        )
    )


@router.get("", response_model=APIResponse[SearchResponse])
@limiter.limit("100/minute")
async def search_unified(
    request: Request,
    q: str = Query(..., description="Search query"),
    mode: str = Query(
        "auto",
        description="Search mode: auto, local, global, or articles",
    ),
    entity_names: str | None = Query(None, description="Comma-separated entity names (local mode)"),
    max_tokens: int | None = Query(None, description="Max context tokens (local/global mode)"),
    community_level: int = Query(0, ge=0, le=10, description="Community level (global mode)"),
    threshold: float = Query(
        0.0, ge=0.0, le=1.0, description="Similarity threshold (articles mode)"
    ),
    limit: int = Query(20, ge=1, le=100, description="Max results (articles mode)"),
    category: str | None = Query(None, description="Category filter (articles mode)"),
    _: str = Depends(verify_api_key),
    local_engine: LocalSearchEngine = Depends(deps.Endpoints.get_local_engine),
    global_engine: GlobalSearchEngine = Depends(deps.Endpoints.get_global_engine),
    vector_repo: VectorRepo = Depends(deps.Endpoints.get_vector_repo),
    llm: LLMClient = Depends(deps.Endpoints.get_llm),
) -> APIResponse[SearchResponse]:
    """Unified search endpoint with automatic mode routing.

    mode=auto: routes based on query characteristics (default: local)
    mode=local: entity-focused graph Q&A
    mode=global: community-level aggregated analysis
    mode=articles: pgvector similarity search
    """
    if mode == "articles":
        # Delegate to search_articles logic
        try:
            embeddings = await llm.batch_embed([q])
            query_vector = embeddings[0]
        except Exception:
            raise HTTPException(status_code=503, detail="Embedding service unavailable")

        if not query_vector:
            raise HTTPException(status_code=503, detail="Embedding service unavailable")

        query_tokens = q.split()

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

        return success_response(
            SearchResponse(
                query=q,
                answer=f"Found {len(sources)} similar articles.",
                context_tokens=0,
                confidence=(
                    float(similar[0].hybrid_score)
                    if (similar and similar[0].hybrid_score is not None)
                    else float(similar[0].similarity) if similar else 0.0
                ),
                search_type="articles",
                entities=[],
                sources=sources,
                metadata={"total_results": len(sources), "threshold": threshold},
            )
        )

    if mode == "global" or mode == "auto":
        try:
            result = await global_engine.search(
                query=q, community_level=community_level, use_llm=False
            )
            return success_response(_result_to_response(result, "global"))
        except Exception as exc:
            if "neo4j" in str(exc).lower() or "graph" in str(exc).lower():
                raise HTTPException(status_code=503, detail="Graph service unavailable")
            raise HTTPException(status_code=503, detail="LLM service unavailable")

    # Default: local (mode=local or mode=auto with local preference)
    try:
        names: list[str] | None = (
            [n.strip() for n in entity_names.split(",") if n.strip()] if entity_names else None
        )
        result = await local_engine.search(
            query=q, max_tokens=max_tokens, entity_names=names, use_llm=False
        )
        return success_response(_result_to_response(result, "local"))
    except Exception as exc:
        if "neo4j" in str(exc).lower() or "graph" in str(exc).lower():
            raise HTTPException(status_code=503, detail="Graph service unavailable")
        raise HTTPException(status_code=503, detail="LLM service unavailable")
