# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Source configuration repository for database operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from core.db import SourceAuthority as SourceAuthorityRow, SourceConfig as SourceConfigRow
from core.observability import get_logger
from modules.ingestion.domain.models import SourceConfig

if TYPE_CHECKING:
    from core.protocols import RelationalPool

log = get_logger(__name__)


class SourceConfigRepo:
    """Repository for source configuration persistence.

    Provides database operations for SourceConfig and preset credibility lookups.

    Implements: SourceRepository

    Args:
        pool: Relational database connection pool.
    """

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    async def get(self, source_id: str) -> SourceConfig | None:
        """Get a source configuration by ID.

        Args:
            source_id: The unique source identifier.

        Returns:
            SourceConfig if found, None otherwise.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(SourceConfigRow).where(SourceConfigRow.id == source_id)
            )
            source = result.scalar_one_or_none()
            if source is None:
                return None
            return self._to_config(source)

    async def get_by_url(self, url: str) -> SourceConfig | None:
        """Get a source configuration by URL.

        Args:
            url: The feed URL.

        Returns:
            SourceConfig if found, None otherwise.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(SourceConfigRow).where(SourceConfigRow.url == url)
            )
            source = result.scalar_one_or_none()
            if source is None:
                return None
            return self._to_config(source)

    async def get_credibility(self, host: str) -> float | None:
        """Get preset credibility for a host.

        Primary lookup is the ``source_authorities`` table, which stores a
        unique ``host`` column — an exact, index-friendly match. Falls back
        to scanning ``source_configs`` whose URL authority equals ``host``
        (URLs are parsed in Python; a substring ``contains`` match would
        false-positive on hosts embedded in paths, e.g.
        ``https://a.com/b.github.com/feed``).

        This is used by CredibilityCheckerNode for the priority hierarchy.

        Args:
            host: The hostname to look up.

        Returns:
            Preset credibility score if found, None otherwise.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(SourceAuthorityRow.authority).where(SourceAuthorityRow.host == host)
            )
            authority = result.scalar_one_or_none()
            if authority is not None:
                return float(authority)

            # Fallback: match SourceConfig rows by parsed URL authority.
            # Order deterministically and use first() — multiple sources may
            # carry a credibility value and scalar_one_or_none would raise.
            rows = await session.execute(
                select(SourceConfigRow)
                .where(SourceConfigRow.credibility.is_not(None))
                .order_by(SourceConfigRow.updated_at.desc())
            )
            for source in rows.scalars():
                try:
                    if urlparse(source.url or "").netloc.lower() == host.lower():
                        return float(source.credibility) if source.credibility is not None else None
                except ValueError:
                    continue
            return None

    async def list_sources(
        self,
        enabled_only: bool = True,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[SourceConfig]:
        """List all sources with optional pagination.

        Args:
            enabled_only: If True, only return enabled sources.
            limit: Maximum number of results (None = no limit).
            offset: Result offset (None = start from beginning).

        Returns:
            List of source configurations.
        """
        async with self._pool.session() as session:
            query = select(SourceConfigRow)
            if enabled_only:
                query = query.where(SourceConfigRow.enabled.is_(True))
            query = query.order_by(SourceConfigRow.name)
            if limit is not None:
                query = query.limit(limit)
            if offset is not None:
                query = query.offset(offset)
            result = await session.execute(query)
            return [self._to_config(s) for s in result.scalars().all()]

    async def count_sources(self, enabled_only: bool = True) -> int:
        """Count sources matching the filter.

        Args:
            enabled_only: If True, only count enabled sources.

        Returns:
            Number of matching sources.
        """
        async with self._pool.session() as session:
            query = select(func.count(SourceConfigRow.id))
            if enabled_only:
                query = query.where(SourceConfigRow.enabled.is_(True))
            result = await session.execute(query)
            return result.scalar() or 0

    async def upsert(self, config: SourceConfig) -> SourceConfig:
        """Create or update a source configuration.

        Args:
            config: Source configuration to persist.

        Returns:
            The persisted source configuration.
        """
        async with self._pool.session() as session:
            values = {
                "id": config.id,
                "name": config.name,
                "url": config.url,
                "source_type": config.source_type,
                "enabled": config.enabled,
                "interval_minutes": config.interval_minutes,
                "per_host_concurrency": config.per_host_concurrency,
                "credibility": config.credibility,
                "tier": config.tier,
                "last_crawl_time": config.last_crawl_time,
                "etag": config.etag,
                "last_modified": config.last_modified,
                "updated_at": datetime.now(UTC),
            }

            stmt = insert(SourceConfigRow).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "name": stmt.excluded.name,
                    "url": stmt.excluded.url,
                    "source_type": stmt.excluded.source_type,
                    "enabled": stmt.excluded.enabled,
                    "interval_minutes": stmt.excluded.interval_minutes,
                    "per_host_concurrency": stmt.excluded.per_host_concurrency,
                    "credibility": stmt.excluded.credibility,
                    "tier": stmt.excluded.tier,
                    "last_crawl_time": stmt.excluded.last_crawl_time,
                    "etag": stmt.excluded.etag,
                    "last_modified": stmt.excluded.last_modified,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            # RETURNING reads the row written by this very statement — a
            # separate SELECT could race with a concurrent upsert and read
            # a snapshot without the row (NoResultFound) or stale data.
            stmt = stmt.returning(SourceConfigRow)
            result = await session.execute(stmt)
            # Consume the row BEFORE commit: commit releases the underlying
            # connection/result set, and the DuckDB driver then fails the
            # deferred scalar_one() with "No open result set".
            config = self._to_config(result.scalar_one())
            await session.commit()
            return config

    async def delete(self, source_id: str) -> bool:
        """Delete a source configuration.

        Args:
            source_id: The source ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(SourceConfigRow).where(SourceConfigRow.id == source_id)
            )
            source = result.scalar_one_or_none()
            if source is None:
                return False
            session.delete(source)
            await session.commit()
            return True

    async def update_crawl_state(
        self,
        source_id: str,
        last_crawl_time: datetime | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        """Update crawl state after successful fetch or auto-disable.

        Args:
            source_id: The source ID.
            last_crawl_time: Timestamp of last successful crawl.
            etag: HTTP ETag if available.
            last_modified: HTTP Last-Modified if available.
            enabled: Set enabled state (used by auto-disable on consecutive failures).
        """
        values = {
            "updated_at": datetime.now(UTC),
        }
        if last_crawl_time is not None:
            values["last_crawl_time"] = last_crawl_time
        if etag is not None:
            values["etag"] = etag
        if last_modified is not None:
            values["last_modified"] = last_modified
        if enabled is not None:
            values["enabled"] = enabled

        async with self._pool.session() as session:
            await session.execute(
                update(SourceConfigRow).where(SourceConfigRow.id == source_id).values(**values)
            )
            await session.commit()

    @staticmethod
    def _to_config(source: SourceConfigRow) -> SourceConfig:
        """Convert ORM model to dataclass.

        Args:
            source: SourceConfigRow ORM instance.

        Returns:
            SourceConfig dataclass instance.
        """
        return SourceConfig(
            id=source.id,
            name=source.name,
            url=source.url,
            source_type=source.source_type,
            enabled=source.enabled,
            interval_minutes=source.interval_minutes,
            per_host_concurrency=source.per_host_concurrency,
            credibility=float(source.credibility) if source.credibility is not None else None,
            tier=source.tier,
            last_crawl_time=source.last_crawl_time,
            etag=source.etag,
            last_modified=source.last_modified,
        )
