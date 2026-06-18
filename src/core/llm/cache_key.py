# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Stable cache key generator for LLM responses.

Generates cache keys that exclude non-semantic fields, ensuring
that changes to tracking metadata (article_id, task_id, etc.) do
not invalidate the cache when the semantic content is unchanged.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Fields that do not affect LLM output semantics.
# Changes to these fields should NOT invalidate the cache.
NON_SEMANTIC_FIELDS: frozenset[str] = frozenset(
    {
        "article_id",
        "task_id",
        "timestamp",
        "request_id",
        "trace_id",
    }
)


def build_stable_cache_key(call_point: str, payload: dict[str, Any]) -> str:
    """Build a stable cache key excluding non-semantic fields.

    Removes non-semantic fields (article_id, task_id, timestamp, etc.)
    from the payload, then generates a normalized hash. This ensures
    that changes to tracking metadata do not invalidate the cache when
    the semantic content is unchanged.

    Args:
        call_point: The call point identifier (e.g., "classifier").
        payload: The request payload dictionary.

    Returns:
        Cache key in format: cache:llm:v2:{call_point}:{sha256[:16]}
    """
    # Filter out non-semantic fields
    semantic_payload = {k: v for k, v in payload.items() if k not in NON_SEMANTIC_FIELDS}

    # Normalized serialization with sorted keys
    normalized = json.dumps(semantic_payload, sort_keys=True, ensure_ascii=False)

    # Generate 16-char SHA256 digest
    stable_hash = hashlib.sha256(normalized.encode()).hexdigest()[:16]

    return f"cache:llm:v2:{call_point}:{stable_hash}"
