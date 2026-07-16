# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

"""Content API endpoints."""

from api.endpoints.content.articles import router as articles_router
from api.endpoints.content.pipeline import router as pipeline_router
from api.endpoints.content.search import router as search_router
from api.endpoints.content.sources import router as sources_router

__all__ = ["articles_router", "pipeline_router", "search_router", "sources_router"]
