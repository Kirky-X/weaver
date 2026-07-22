# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Re-export layer for web search protocol symbols.

The canonical definitions live in ``core.protocols.web_search`` to match
the project's Protocol centralization convention (all Protocol interfaces
are defined under ``src/core/protocols/`` and re-exported from
``core.protocols``).

This module exists so callers can import from a path that mirrors the
concrete implementation package (``modules.search.web``):
    from modules.search.web.protocol import BingSearchProtocol, BingSearchResult

Both import paths work — pick whichever is most readable in context.
"""

from __future__ import annotations

from core.protocols.web_search import (
    BingSearchMode,
    BingSearchProtocol,
    BingSearchResult,
    BingTimeFilter,
    QueryExpanderProtocol,
)

__all__ = [
    "BingSearchMode",
    "BingSearchProtocol",
    "BingSearchResult",
    "BingTimeFilter",
    "QueryExpanderProtocol",
]
