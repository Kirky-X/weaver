"""Admin API endpoints."""

from api.endpoints.admin.admin import router
from api.endpoints.admin.monitoring import router as monitoring_router

# Include monitoring routes under /admin prefix
router.include_router(monitoring_router)

__all__ = ["router"]
