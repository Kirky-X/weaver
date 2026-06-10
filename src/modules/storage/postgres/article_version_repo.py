# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Repository for article version history.

Implements: VersionRepository
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from core.db.models import ArticleVersion
from core.observability.logging import get_logger
from core.protocols import RelationalPool

log = get_logger(__name__)


class ArticleVersionRepo:
    """Repository for article version history.

    Stores snapshots of article content before updates, enabling
    audit trails and change tracking.

    Implements: VersionRepository

    Args:
        pool: Relational database connection pool.
    """

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    async def create_version(
        self,
        article_id: uuid.UUID,
        title: str,
        body: str,
        summary: str | None,
        category: str | None,
        score: float | None,
        changed_fields: list[str],
    ) -> ArticleVersion:
        """Create a version snapshot before updating.

        Auto-increments the version number based on the latest
        existing version for the article.

        Args:
            article_id: UUID of the article.
            title: Article title at this version.
            body: Article body at this version.
            summary: Article summary at this version.
            category: Article category at this version.
            score: Article score at this version.
            changed_fields: List of field names that changed.

        Returns:
            The created ArticleVersion instance.
        """
        async with self._pool.session() as session:
            # Get current max version for this article
            result = await session.execute(
                select(func.max(ArticleVersion.version)).where(
                    ArticleVersion.article_id == article_id
                )
            )
            max_version = result.scalar_one_or_none()
            next_version = (max_version or 0) + 1

            version = ArticleVersion(
                article_id=article_id,
                version=next_version,
                title=title,
                body=body,
                summary=summary,
                category=category,
                score=score,
                changed_fields=changed_fields or None,
            )
            session.add(version)
            await session.commit()

            log.debug(
                "version_created",
                article_id=str(article_id),
                version=next_version,
                changed_fields=changed_fields,
            )
            return version

    async def get_version_history(
        self, article_id: uuid.UUID, limit: int = 10
    ) -> list[ArticleVersion]:
        """Get version history for an article, newest first.

        Args:
            article_id: UUID of the article.
            limit: Maximum number of versions to return.

        Returns:
            List of ArticleVersion instances ordered by version desc.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(ArticleVersion)
                .where(ArticleVersion.article_id == article_id)
                .order_by(ArticleVersion.version.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_latest_version(self, article_id: uuid.UUID) -> ArticleVersion | None:
        """Get the most recent version.

        Args:
            article_id: UUID of the article.

        Returns:
            The latest ArticleVersion, or None if no versions exist.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(ArticleVersion)
                .where(ArticleVersion.article_id == article_id)
                .order_by(ArticleVersion.version.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()
