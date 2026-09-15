# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Source authority repository."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

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

    # Concurrent get_or_create calls race on the unique host constraint;
    # the loser re-queries and returns the winner's row.
    MAX_GET_OR_CREATE_ATTEMPTS = 3

    async def get_or_create(
        self,
        host: str,
        auto_score: float | None = None,
        description: str | None = None,
    ) -> SourceAuthority:
        """Get existing authority or create a new entry with defaults.

        Handles the concurrent-creation race: when two calls both observe
        no row and insert, the unique constraint on ``host`` rejects the
        second commit; that call re-queries and returns the existing row
        (corr#462) instead of crashing.

        Args:
            host: Source hostname.
            auto_score: Optional auto-computed score.
            description: Optional description (defaults to host if not provided).

        Returns:
            SourceAuthority record.
        """
        last_exc: IntegrityError | None = None
        for _attempt in range(self.MAX_GET_OR_CREATE_ATTEMPTS):
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
                    try:
                        await session.commit()
                    except IntegrityError as exc:
                        await session.rollback()
                        last_exc = exc
                        log.debug("source_authority_create_race_retry", host=host)
                        continue
                    await session.refresh(authority)
                    log.info("source_authority_created", host=host, description=default_desc)

                return authority

        raise (
            last_exc
            if last_exc
            else RuntimeError(
                f"get_or_create({host!r}) failed after {self.MAX_GET_OR_CREATE_ATTEMPTS} attempts"
            )
        )

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

        final_score is computed atomically in the UPDATE expression
        (corr#463): the old SELECT-then-UPDATE could base final_score on a
        stale manual_score committed by a reviewer between the two
        statements. ``COALESCE(manual_score, auto_score)`` preserves the
        previous fallback (no manual score → final = auto).
        """
        async with self._pool.session() as session:
            await session.execute(
                update(SourceAuthority)
                .where(SourceAuthority.host == host)
                .values(
                    auto_score=auto_score,
                    needs_review=False,
                    updated_at=datetime.now(UTC),
                    final_score=func.round(
                        0.7 * auto_score
                        + 0.3 * func.coalesce(SourceAuthority.manual_score, auto_score),
                        2,
                    ),
                )
            )
            await session.commit()
