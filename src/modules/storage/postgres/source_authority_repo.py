# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Source authority repository."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update

from core.db.models import SourceAuthority
from core.observability.logging import get_logger
from core.protocols import RelationalPool

log = get_logger("source_authority_repo")


class SourceAuthorityRepo:
    """Repository for source authority scores.

    Implements: EntityRepository (partial)

    Args:
        pool: Relational database connection pool.
    """

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    async def get_or_create(
        self,
        host: str,
        auto_score: float | None = None,
    ) -> SourceAuthority:
        """Get existing authority or create a new entry with defaults.

        Args:
            host: Source hostname.
            auto_score: Optional auto-computed score.

        Returns:
            SourceAuthority record.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(SourceAuthority).where(SourceAuthority.host == host)
            )
            authority = result.scalar_one_or_none()

            if authority is None:
                authority = SourceAuthority(
                    host=host,
                    authority=0.50,
                    tier=3,
                    needs_review=True,
                    auto_score=auto_score,
                )
                session.add(authority)
                await session.commit()
                await session.refresh(authority)
                log.info("source_authority_created", host=host)

            return authority

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
                .where(SourceAuthority.needs_review == True)  # noqa: E712
                .order_by(SourceAuthority.host)
            )
            return list(result.scalars().all())

    async def list_all(self) -> list[SourceAuthority]:
        """Get all authorities."""
        async with self._pool.session() as session:
            result = await session.execute(select(SourceAuthority).order_by(SourceAuthority.host))
            return list(result.scalars().all())

    async def update_auto_score(self, host: str, auto_score: float) -> None:
        """Update auto-computed authority score."""
        async with self._pool.session() as session:
            await session.execute(
                update(SourceAuthority)
                .where(SourceAuthority.host == host)
                .values(
                    auto_score=auto_score,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()
