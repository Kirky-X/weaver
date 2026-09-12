# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Container registration entry point for API endpoint dependencies.

This module only provides the container registration lifecycle hooks
(``Endpoints.initialize`` / ``Endpoints.reset``). All dependency getters
live in :mod:`api.dependencies` and MUST be consumed from there via
FastAPI's ``Depends()`` pattern:

    from fastapi import Depends
    from api.dependencies import get_relational_pool

    @router.get("/items")
    async def list_items(pool=Depends(get_relational_pool)): ...

All getters in :mod:`api.dependencies` return Protocol types, not concrete
implementations.
"""

from __future__ import annotations

from core.observability import get_logger

log = get_logger(__name__)


class Endpoints:
    """Container registration entry point for API dependencies.

    ``initialize`` registers the application container globally so that
    :mod:`api.dependencies` getters can resolve services; ``reset`` clears
    it for test isolation.
    """

    @classmethod
    def initialize(cls, container: object) -> None:
        """Initialize all endpoints dependencies from container.

        This method is called by Container.startup() to ensure the
        global container is registered. The actual dependency resolution
        now happens via :mod:`api.dependencies` using the container.

        Args:
            container: Application container with all services.

        """
        from container import set_container

        set_container(container)

        log.info(
            "endpoints_initialized",
            relational_type=getattr(container, "relational_pool_type", "unknown"),
            graph_type=getattr(container, "graph_pool_type", None),
            cache_type=(
                type(getattr(container, "_cache_client", None)).__name__
                if hasattr(container, "_cache_client") and container._cache_client is not None
                else "none"
            ),
            llm_enabled=getattr(container, "_llm_client", None) is not None,
            search_enabled=getattr(container, "_local_search_engine", None) is not None,
        )

    @classmethod
    def reset(cls) -> None:
        """Reset all cached state for test isolation.

        Clears the global container so that subsequent dependency
        lookups will raise HTTPException(503) until a new container
        is set via :func:`container.set_container`.
        """
        import container

        container.reset_container()
