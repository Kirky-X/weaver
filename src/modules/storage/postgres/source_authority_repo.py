# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Source authority repository."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update

from core.db import SourceAuthority
from core.observability import get_logger
from core.protocols import RelationalPool

log = get_logger(__name__)


class SourceAuthorityRepo:
    """Repository for source authority scores.

    Implements: SourceAuthorityRepository

    Args:
        pool: Relational database connection pool.
    """

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    async def get_or_create(
        self,
        host: str,
        auto_score: float | None = None,
        description: str | None = None,
    ) -> SourceAuthority:
        """Get existing authority or create a new entry with defaults.

        Args:
            host: Source hostname.
            auto_score: Optional auto-computed score.
            description: Optional description (defaults to host if not provided).

        Returns:
            SourceAuthority record.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(SourceAuthority).where(SourceAuthority.host == host)
            )
            authority = result.scalar_one_or_none()

            if authority is None:
                # Use host as default description if not provided
                default_desc = description or host
                authority = SourceAuthority(
                    host=host,
                    authority=0.50,
                    tier=3,
                    description=default_desc,
                    needs_review=True,
                    auto_score=auto_score,
                )
                session.add(authority)
                await session.commit()
                await session.refresh(authority)
                log.info("source_authority_created", host=host, description=default_desc)

            return authority

    async def get(self, host: str) -> SourceAuthority | None:
        """Get existing authority record without creating a new one.

        Args:
            host: Source hostname.

        Returns:
            SourceAuthority record if exists, None otherwise.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(SourceAuthority).where(SourceAuthority.host == host)
            )
            return result.scalar_one_or_none()

    async def update_authority(
        self,
        host: str,
        authority: float,
        tier: int | None = None,
        needs_review: bool = False,
        description: str | None = None,
    ) -> None:
        """Update authority score for a host.

        Args:
            host: Source hostname.
            authority: Authority score (0.0-1.0).
            tier: Optional tier level (1-5).
            needs_review: Whether needs manual review.
            description: Optional description.
        """
        values: dict = {
            "authority": authority,
            "needs_review": needs_review,
            "updated_at": datetime.now(UTC),
        }
        if tier is not None:
            values["tier"] = tier
        if description is not None:
            values["description"] = description

        async with self._pool.session() as session:
            await session.execute(
                update(SourceAuthority).where(SourceAuthority.host == host).values(**values)
            )
            await session.commit()

    async def get_needs_review(self) -> list[SourceAuthority]:
        """Get all authorities needing review."""
        async with self._pool.session() as session:
            result = await session.execute(
                select(SourceAuthority)
                .where(SourceAuthority.needs_review.is_(True))
                .order_by(SourceAuthority.host)
            )
            return list(result.scalars().all())

    async def list_all(self) -> list[SourceAuthority]:
        """Get all authorities."""
        async with self._pool.session() as session:
            result = await session.execute(select(SourceAuthority).order_by(SourceAuthority.host))
            return list(result.scalars().all())

    async def update_auto_score(self, host: str, auto_score: float) -> None:
        """Update auto-computed authority score.

        Also clears needs_review flag since auto-computed scores
        represent system's assessment, not requiring human review.
        Recalculates final_score as weighted average of auto and manual scores.
        """
        async with self._pool.session() as session:
            # Get current record to compute final_score
            result = await session.execute(
                select(SourceAuthority).where(SourceAuthority.host == host)
            )
            record = result.scalar_one_or_none()

            values: dict = {
                "auto_score": auto_score,
                "needs_review": False,
                "updated_at": datetime.now(UTC),
            }

            # Compute final_score: weighted average (70% auto, 30% manual)
            if record is not None:
                manual = record.manual_score if record.manual_score is not None else None
                if manual is not None:
                    values["final_score"] = round(0.7 * auto_score + 0.3 * manual, 2)
                else:
                    values["final_score"] = round(auto_score, 2)

            await session.execute(
                update(SourceAuthority).where(SourceAuthority.host == host).values(**values)
            )
            await session.commit()

    async def update_manual_score(self, host: str, manual_score: float) -> None:
        """Update manual authority score and recalculate final_score.

        Args:
            host: Source hostname.
            manual_score: Manually assigned score (0.0-1.0).
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(SourceAuthority).where(SourceAuthority.host == host)
            )
            record = result.scalar_one_or_none()

            values: dict = {
                "manual_score": manual_score,
                "updated_at": datetime.now(UTC),
            }

            if record is not None and record.auto_score is not None:
                values["final_score"] = round(0.7 * record.auto_score + 0.3 * manual_score, 2)
            else:
                values["final_score"] = round(manual_score, 2)

            await session.execute(
                update(SourceAuthority).where(SourceAuthority.host == host).values(**values)
            )
            await session.commit()

    async def increment_article_count(self, host: str) -> None:
        """Increment article_count and update last_crawled_at for a source."""
        async with self._pool.session() as session:
            await session.execute(
                update(SourceAuthority)
                .where(SourceAuthority.host == host)
                .values(
                    article_count=SourceAuthority.article_count + 1,
                    last_crawled_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()
