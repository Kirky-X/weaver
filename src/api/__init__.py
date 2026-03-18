# Copyright (c) 2026 KirkyX. All Rights Reserved
"""API module - FastAPI application and endpoints.

This module provides:
- router: Unified API router with all endpoints
- endpoints: API endpoint modules (articles, sources, pipeline, etc.)
- middleware: Request middleware (auth, rate limiting)
- schemas: Pydantic models for request/response

Example usage:
    from api.router import api_router
    app.include_router(api_router)
"""

from api.router import api_router

__all__ = ["api_router"]
