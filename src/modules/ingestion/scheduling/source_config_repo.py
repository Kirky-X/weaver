# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Source configuration repository for database operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from core.db.models import Source
from core.observability.logging import get_logger
from modules.ingestion.domain.models import SourceConfig

if TYPE_CHECKING:
    from core.protocols import RelationalPool

log = get_logger("source_config_repo")


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
            result = await session.execute(select(Source).where(Source.id == source_id))
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
            result = await session.execute(select(Source).where(Source.url == url))
            source = result.scalar_one_or_none()
            if source is None:
                return None
            return self._to_config(source)

    async def get_credibility(self, host: str) -> float | None:
        """Get preset credibility for a host.

        Looks up source by extracting host from stored URLs.
        This is used by CredibilityCheckerNode for the priority hierarchy.

        Args:
            host: The hostname to look up.

        Returns:
            Preset credibility score if found, None otherwise.
        """
        async with self._pool.session() as session:
            # Match sources where URL contains the host
            result = await session.execute(
                select(Source).where(Source.url.contains(host), Source.credibility.is_not(None))
            )
            source = result.scalar_one_or_none()
            if source and source.credibility is not None:
                return float(source.credibility)
            return None

    async def list_sources(self, enabled_only: bool = True) -> list[SourceConfig]:
        """List all sources.

        Args:
            enabled_only: If True, only return enabled sources.

        Returns:
            List of source configurations.
        """
        async with self._pool.session() as session:
            query = select(Source)
            if enabled_only:
                query = query.where(Source.enabled == True)  # noqa: E712
            result = await session.execute(query.order_by(Source.name))
            return [self._to_config(s) for s in result.scalars().all()]

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

            stmt = insert(Source).values(**values)
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
            await session.execute(stmt)
            await session.commit()

            # Fetch the persisted record
            result = await session.execute(select(Source).where(Source.id == config.id))
            return self._to_config(result.scalar_one())

    async def delete(self, source_id: str) -> bool:
        """Delete a source configuration.

        Args:
            source_id: The source ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        async with self._pool.session() as session:
            result = await session.execute(select(Source).where(Source.id == source_id))
            source = result.scalar_one_or_none()
            if source is None:
                return False
            session.delete(source)
            await session.commit()
            return True

    async def update_crawl_state(
        self,
        source_id: str,
        last_crawl_time: datetime,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        """Update crawl state after successful fetch.

        Args:
            source_id: The source ID.
            last_crawl_time: Timestamp of last successful crawl.
            etag: HTTP ETag if available.
            last_modified: HTTP Last-Modified if available.
        """
        values = {
            "last_crawl_time": last_crawl_time,
            "updated_at": datetime.now(UTC),
        }
        if etag is not None:
            values["etag"] = etag
        if last_modified is not None:
            values["last_modified"] = last_modified

        async with self._pool.session() as session:
            await session.execute(update(Source).where(Source.id == source_id).values(**values))
            await session.commit()

    @staticmethod
    def _to_config(source: Source) -> SourceConfig:
        """Convert ORM model to dataclass.

        Args:
            source: Source ORM instance.

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
