# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Articles API endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import asc, desc, select

from api.dependencies import get_postgres_pool
from api.middleware.auth import verify_api_key
from api.middleware.rate_limit import limiter
from api.schemas.response import APIResponse, success_response
from core.db.models import Article, CategoryType
from core.db.postgres import PostgresPool
from core.observability.logging import get_logger

log = get_logger("articles_api")

router = APIRouter(prefix="/articles", tags=["articles"])


# ── Request/Response Models ─────────────────────────────────────


class ArticleListResponse(BaseModel):
    """Response model for article list."""

    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    total_pages: int


class ArticleDetailResponse(BaseModel):
    """Response model for article detail."""

    id: str
    source_url: str
    source_host: str | None
    is_news: bool
    title: str
    body: str
    category: str | None
    language: str | None
    region: str | None
    summary: str | None
    event_time: datetime | None
    subjects: list[str] | None
    key_data: list[str] | None
    impact: str | None
    score: float | None
    sentiment: str | None
    sentiment_score: float | None
    primary_emotion: str | None
    credibility_score: float | None
    source_credibility: float | None
    cross_verification: float | None
    content_check_score: float | None
    publish_time: datetime | None
    created_at: datetime
    updated_at: datetime


# ── Helpers ─────────────────────────────────────────────────────


def _article_to_dict(article: Article) -> dict[str, Any]:
    """Convert Article model to dictionary."""
    return {
        "id": str(article.id),
        "source_url": article.source_url,
        "source_host": article.source_host,
        "is_news": article.is_news,
        "title": article.title,
        "body": article.body,
        "category": article.category.value if article.category else None,
        "language": article.language,
        "region": article.region,
        "summary": article.summary,
        "event_time": article.event_time.isoformat() if article.event_time else None,
        "subjects": article.subjects,
        "key_data": article.key_data,
        "impact": article.impact,
        "score": float(article.score) if article.score else None,
        "sentiment": article.sentiment,
        "sentiment_score": float(article.sentiment_score) if article.sentiment_score else None,
        "primary_emotion": article.primary_emotion.value if article.primary_emotion else None,
        "credibility_score": (
            float(article.credibility_score) if article.credibility_score else None
        ),
        "source_credibility": (
            float(article.source_credibility) if article.source_credibility else None
        ),
        "cross_verification": (
            float(article.cross_verification) if article.cross_verification else None
        ),
        "content_check_score": (
            float(article.content_check_score) if article.content_check_score else None
        ),
        "publish_time": article.publish_time.isoformat() if article.publish_time else None,
        "created_at": article.created_at.isoformat(),
        "updated_at": article.updated_at.isoformat(),
    }


# ── Endpoints ───────────────────────────────────────────────────


@router.get("", response_model=APIResponse[ArticleListResponse])
@limiter.limit("100/minute")
async def list_articles(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    category: str | None = Query(None, description="Filter by category"),
    source_host: str | None = Query(None, description="Filter by source host"),
    min_score: float | None = Query(None, ge=0, le=1, description="Minimum score filter"),
    min_credibility: float | None = Query(
        None, ge=0, le=1, description="Minimum credibility filter"
    ),
    sort_by: str = Query(
        "publish_time", description="Sort field: publish_time, score, credibility_score, created_at"
    ),
    sort_order: str = Query("desc", description="Sort order: asc, desc"),
    _: str = Depends(verify_api_key),
    pool: PostgresPool = Depends(get_postgres_pool),
) -> APIResponse[ArticleListResponse]:
    """Get a paginated list of articles with optional filters.

    Args:
        page: Page number (1-indexed).
        page_size: Items per page.
        category: Filter by category.
        source_host: Filter by source hostname.
        min_score: Minimum score filter (0-1).
        min_credibility: Minimum credibility score filter (0-1).
        sort_by: Field to sort by.
        sort_order: Sort order (asc or desc).
        _: Verified API key.
        pool: Postgres connection pool.

    Returns:
        Paginated list of articles.

    """
    async with pool.session() as session:
        from sqlalchemy import func

        query = select(Article)

        filters = []
        if category:
            try:
                cat = CategoryType(category)
                filters.append(Article.category == cat)
            except ValueError:
                pass
        if source_host:
            filters.append(Article.source_host == source_host)
        if min_score is not None:
            filters.append(Article.score >= min_score)
        if min_credibility is not None:
            filters.append(Article.credibility_score >= min_credibility)

        for f in filters:
            query = query.where(f)

        count_query = select(func.count()).select_from(query.subquery())
        count_result = await session.execute(count_query)
        total = count_result.scalar() or 0

        offset = (page - 1) * page_size
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0

        # Validate sort_by against whitelist to prevent attribute injection
        ALLOWED_SORT_COLUMNS = {"publish_time", "score", "credibility_score", "created_at"}
        if sort_by not in ALLOWED_SORT_COLUMNS:
            sort_by = "publish_time"

        sort_column = getattr(Article, sort_by, Article.publish_time)
        if sort_order == "desc":
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(asc(sort_column))

        query = query.offset(offset).limit(page_size)

        result = await session.execute(query)
        articles = result.scalars().all()

        return success_response(
            ArticleListResponse(
                items=[_article_to_dict(a) for a in articles],
                total=total,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
            )
        )


@router.get("/{article_id}", response_model=APIResponse[ArticleDetailResponse])
async def get_article(
    article_id: str,
    _: str = Depends(verify_api_key),
    pool: PostgresPool = Depends(get_postgres_pool),
) -> APIResponse[ArticleDetailResponse]:
    """Get detailed information about a specific article.

    Args:
        article_id: The article UUID.
        _: Verified API key.
        pool: Postgres connection pool.

    Returns:
        Article detail.

    Raises:
        HTTPException: If article not found.

    """
    try:
        article_uuid = uuid.UUID(article_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid article ID format",
        )

    async with pool.session() as session:
        result = await session.execute(select(Article).where(Article.id == article_uuid))
        article = result.scalar_one_or_none()

        if article is None:
            raise HTTPException(
                status_code=404,
                detail=f"Article '{article_id}' not found",
            )

        return success_response(ArticleDetailResponse(**_article_to_dict(article)))
