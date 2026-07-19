# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Web search module — Bing-backed fallback data source for search API.

Public API:
    - ``BingSearchProtocol``: typing.Protocol implemented by web search backends.
    - ``BingSearchResult``: frozen dataclass for a single search result.
    - ``BingSearcher``: concrete Bing HTML search backend (reuses BaseFetcher).
"""

from __future__ import annotations

from modules.search.web.bing_searcher import BingSearcher
from modules.search.web.protocol import BingSearchProtocol, BingSearchResult

__all__ = ["BingSearchProtocol", "BingSearchResult", "BingSearcher"]
