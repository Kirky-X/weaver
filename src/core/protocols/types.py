# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Shared type definitions used in Protocol signatures.

This module re-exports type definitions that are used in Protocol method
signatures so that the protocols layer does not depend directly on the
DB layer (``core.db``) or the types package (``core.types``).

Importing from this module is preferred within ``core.protocols``:
    from core.protocols.types import PersistStatus, PipelineState

Re-exported types:
    - PersistStatus: Article persistence status enum (defined in core.db.models.base)
    - PipelineState: TypedDict for pipeline state (defined in core.types.pipeline_state)
    - ArticleView, EntityView, EventView, CommunityView: View models
      (defined in core.models.shared)
    - ArticleSearchResultView, EntitySearchResultView, CommunitySearchResultView:
      Search result view models (defined in core.models.shared)
    - ArticleTitleMeta: TypedDict for batch title lookup (defined here)
"""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

# Import directly from the definition modules (not the package __init__)
# to avoid circular imports:
#   core.protocols -> core.protocols.types -> core.db -> core.protocols
# By importing from core.db.models.base and core.types.pipeline_state
# directly, we bypass the core.db.__init__ which imports core.protocols.
from core.db.models.base import PersistStatus
from core.models.shared import (
    ArticleSearchResultView,
    ArticleView,
    CommunitySearchResultView,
    EntitySearchResultView,
    EntityView,
)
from core.types.pipeline_state import PipelineState


class ArticleTitleMeta(TypedDict):
    """Article metadata returned by ``ArticleRepository.fetch_titles_by_pg_ids``.

    Used by graph-query callers that, after the Article node slim-down
    (design.md §D2), can only read ``pg_id`` from the graph DB and must
    look up the business fields from the relational DB in a batch.
    """

    title: str
    category: str | None
    publish_time: datetime | None
    score: float | None


__all__ = [
    "ArticleSearchResultView",
    "ArticleTitleMeta",
    "ArticleView",
    "CommunitySearchResultView",
    "EntitySearchResultView",
    "EntityView",
    "PersistStatus",
    "PipelineState",
]
