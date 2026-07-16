# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Knowledge cluster caching module.

Provides DuckDB + Parquet based caching for semantic search results.
"""

from modules.knowledge.cache.storage import KnowledgeCache

__all__ = [
    "KnowledgeCache",
]
