# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Search module — Web search and fallback orchestration.

Boundary clarification:
    This package is NOT to be confused with ``modules.knowledge.search``.

    - ``modules.knowledge.search`` — Knowledge graph retrieval engines
      (Local/Global/DRIFT/Hybrid) that read from the project's own
      PostgreSQL / DuckDB / Neo4j / LadybugDB stores.
    - ``modules.search`` (this package) — External web search backends
      (Bing, future Google/DuckDuckGo) used as a fallback data source
      when the knowledge graph returns no results (three-tier empty).

The two packages are deliberately separate to keep the "external data
input" concern decoupled from the "internal knowledge retrieval" concern.
Import paths:
    from modules.knowledge.search import LocalSearchEngine  # internal
    from modules.search.web import BingSearcher              # external
"""

__all__ = []
