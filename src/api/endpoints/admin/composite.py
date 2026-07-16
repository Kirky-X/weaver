# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Admin composite router — aggregates all admin sub-routers.

Each sub-router carries its own ``/admin`` prefix, so the composite itself
has none to avoid double-prefixing (``/admin/admin/...``).
"""

from fastapi import APIRouter

from api.endpoints.admin.api_keys import router as api_keys_router
from api.endpoints.admin.articles import router as articles_router
from api.endpoints.admin.authorities import router as authorities_router
from api.endpoints.admin.memory import router as memory_router
from api.endpoints.admin.monitoring import router as monitoring_router

router = APIRouter(tags=["admin"])
router.include_router(authorities_router)
router.include_router(articles_router)
router.include_router(memory_router)
router.include_router(api_keys_router)
router.include_router(monitoring_router)
