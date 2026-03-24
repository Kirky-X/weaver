# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LLM module type definitions: enums and data classes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LLMType(str, Enum):
    """Type of LLM interaction."""

    CHAT = "chat"
    EMBEDDING = "embedding"
    RERANK = "rerank"


class CallPoint(str, Enum):
    """Pipeline call points that invoke LLM operations."""

    CLASSIFIER = "classifier"
    CLEANER = "cleaner"
    CATEGORIZER = "categorizer"
    MERGER = "merger"
    ANALYZE = "analyze"
    CREDIBILITY_CHECKER = "credibility_checker"
    QUALITY_SCORER = "quality_scorer"
    ENTITY_EXTRACTOR = "entity_extractor"
    ENTITY_RESOLVER = "entity_resolver"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    SEARCH_LOCAL = "search_local"
    SEARCH_GLOBAL = "search_global"
    COMMUNITY_REPORT = "community_report"


@dataclass
class LLMTask:
    """Represents a single LLM operation to be queued and executed.

    Attributes:
        call_point: The pipeline stage initiating this call.
        llm_type: Type of LLM interaction.
        payload: Input data for the LLM call.
        priority: Priority level (lower = higher priority).
        attempt: Current retry count for self-retry logic.
        provider_cfg: Provider configuration (set by QueueManager).
        future: Asyncio future for result delivery.
    """

    call_point: CallPoint
    llm_type: LLMType
    payload: dict[str, Any]
    priority: int = 5
    attempt: int = 0
    provider_cfg: Any = field(default=None, init=False)
    future: asyncio.Future | None = field(default=None, init=False)

    def __lt__(self, other: LLMTask) -> bool:
        """Support PriorityQueue ordering."""
        return self.priority < other.priority
