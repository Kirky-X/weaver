# Copyright (c) 2026 KirkyX. All Rights Reserved
"""HNSW dynamic ef_search manager.

Implements dynamic ef_search strategy for HNSW index based on search mode:
- hybrid: 40 (RRF fusion compensates recall)
- local: 120 (high recall for neighborhood search)
- global: 60 (moderate recall for community-level search)
- drift: 80 (high precision for iterative search)
- latency: 20 (prioritize speed over recall)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.constants import SearchMode
from core.observability import get_logger

if TYPE_CHECKING:
    from core.protocols import RelationalPool

log = get_logger(__name__)


@dataclass
class EfSearchConfig:
    """Configuration for HNSW ef_search values.

    Attributes:
        hybrid: ef_search for hybrid search (RRF fusion compensates recall).
        local: ef_search for local neighborhood search (high recall).
        global_value: ef_search for global community search (moderate recall).
        drift: ef_search for drift/iterative search (high precision).
        latency: ef_search for latency-sensitive endpoints (prioritize speed).
    """

    hybrid: int = 40
    local: int = 120
    global_value: int = 60
    drift: int = 80
    latency: int = 20

    @classmethod
    def from_settings(cls, settings: Any) -> EfSearchConfig:
        """Create config from settings object.

        Args:
            settings: Settings object with search.hnsw.ef_search attributes.

        Returns:
            EfSearchConfig instance.
        """
        return cls(
            hybrid=settings.search.hnsw.ef_search.hybrid,
            local=settings.search.hnsw.ef_search.local,
            global_value=settings.search.hnsw.ef_search.global_value,
            drift=settings.search.hnsw.ef_search.drift,
            latency=settings.search.hnsw.ef_search.latency,
        )


class EfSearchManager:
    """Manages HNSW ef_search parameter dynamically based on search mode.

    This manager allows runtime adjustment of HNSW ef_search parameter
    to optimize for different search scenarios (recall vs latency tradeoff).

    Args:
        pool: Relational database connection pool.
        config: EfSearch configuration with mode-specific values.
    """

    def __init__(
        self,
        pool: RelationalPool | None,
        config: EfSearchConfig | None = None,
    ) -> None:
        self._pool = pool
        self._config = config or EfSearchConfig()

    def get_ef_search(self, mode: SearchMode | str) -> int:
        """Get ef_search value for specified search mode.

        Args:
            mode: Search mode (hybrid, local, global, drift, latency).

        Returns:
            ef_search value for the specified mode.

        Raises:
            ValueError: If mode is not recognized.
        """
        if isinstance(mode, str):
            try:
                mode = SearchMode(mode)
            except ValueError:
                raise ValueError(f"Unknown search mode: {mode}")

        mode_map = {
            SearchMode.HYBRID: self._config.hybrid,
            SearchMode.LOCAL: self._config.local,
            SearchMode.GLOBAL: self._config.global_value,
            SearchMode.DRIFT: self._config.drift,
            SearchMode.LATENCY: self._config.latency,
        }

        return mode_map[mode]

    async def set_ef_search(
        self,
        mode: SearchMode | str,
        value: int | None = None,
    ) -> None:
        """Set HNSW ef_search parameter for the current session.

        Args:
            mode: Search mode to determine ef_search value.
            value: Custom ef_search value (overrides mode-based value).
        """
        if not self._pool:
            return

        ef_search_value = value if value is not None else self.get_ef_search(mode)

        try:
            async with self._pool.session() as session:
                await session.execute(f"SET hnsw.ef_search = {ef_search_value}")
                log.debug(
                    "ef_search_set",
                    mode=str(mode),
                    ef_search=ef_search_value,
                )
        except Exception as exc:
            log.warning(
                "ef_search_set_failed",
                mode=str(mode),
                ef_search=ef_search_value,
                error=str(exc),
                exc_type=type(exc).__name__,
            )

    @asynccontextmanager
    async def apply_ef_search(
        self,
        mode: SearchMode | str,
        value: int | None = None,
    ) -> AsyncIterator[None]:
        """Context manager to apply ef_search for a block of operations.

        Sets ef_search on entry and restores original value on exit.

        Args:
            mode: Search mode to determine ef_search value.
            value: Custom ef_search value (overrides mode-based value).

        Yields:
            None
        """
        if not self._pool:
            yield
            return

        original_ef_search = None
        ef_search_value = value if value is not None else self.get_ef_search(mode)

        try:
            async with self._pool.session() as session:
                # Get current ef_search value
                try:
                    result = await session.execute("SHOW hnsw.ef_search")
                    original_ef_search = result.scalar()
                except Exception:
                    # If we can't get current value, use default
                    original_ef_search = 40

                # Set new ef_search value
                await session.execute(f"SET hnsw.ef_search = {ef_search_value}")
                log.debug(
                    "ef_search_applied",
                    mode=str(mode),
                    ef_search=ef_search_value,
                    original=original_ef_search,
                )

                yield

                # Restore original ef_search value
                if original_ef_search is not None:
                    await session.execute(f"SET hnsw.ef_search = {original_ef_search}")
                    log.debug(
                        "ef_search_restored",
                        ef_search=original_ef_search,
                    )

        except Exception as exc:
            log.warning(
                "ef_search_apply_failed",
                mode=str(mode),
                ef_search=ef_search_value,
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            yield
