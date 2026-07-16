# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""PrefixShape diagnostics for LLM cache miss analysis.

Tracks prefix shape (system prompt, tools schema, payload) stability
per call_point to diagnose cache miss causes. Pure observability —
does NOT influence cache read/write decisions.

Only depends on standard library (hashlib, dataclasses, json).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


def _short_hash(data: str) -> str:
    """Generate 8-char SHA256 digest of input string."""
    return hashlib.sha256(data.encode()).hexdigest()[:8]


@dataclass(frozen=True)
class PrefixShape:
    """Snapshot of LLM request prefix shape.

    Captures the three prefix components that affect DeepSeek auto
    prefix cache: system prompt, tools schema, and payload.

    Attributes:
        system_hash: 8-char hash of system prompt.
        tools_hash: 8-char hash of tools schema (normalized).
        payload_hash: 8-char hash of payload (non-semantic fields excluded).
        call_point: The call point identifier.
    """

    system_hash: str
    tools_hash: str
    payload_hash: str
    call_point: str

    @property
    def prefix_hash(self) -> str:
        """Combined prefix hash (16 chars).

        Returns SHA256[:16] of system:tools:payload concatenation.
        """
        combined = f"{self.system_hash}:{self.tools_hash}:{self.payload_hash}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]


@dataclass
class CacheDiagnostics:
    """Cache miss diagnostics for a single call_point.

    Attributes:
        prefix_hash: Current prefix shape hash (16 chars).
        prefix_changed: Whether prefix changed since last call.
        change_reasons: List of changed components (system/tools/payload).
        server_cache_hit: Server-side cache hit tokens.
        server_cache_miss: Server-side cache miss tokens.
    """

    prefix_hash: str
    prefix_changed: bool
    change_reasons: list[str] = field(default_factory=list)
    server_cache_hit: int = 0
    server_cache_miss: int = 0


def capture_shape(
    call_point: str,
    payload: dict[str, Any],
    system_prompt: str = "",
    tools_schema: list[dict[str, Any]] | None = None,
) -> PrefixShape:
    """Capture current request prefix shape.

    Args:
        call_point: The call point identifier.
        payload: Request payload (non-semantic fields excluded).
        system_prompt: System prompt string.
        tools_schema: Tools schema list (normalized via sort_keys).

    Returns:
        PrefixShape with 8-char hashes for each component.
    """
    system_hash = _short_hash(system_prompt or "")

    if tools_schema is None:
        tools_hash = _short_hash("")
    else:
        # Normalize tools schema: sort keys within each dict, then sort list elements
        normalized_items = [
            json.dumps(item, sort_keys=True, ensure_ascii=False) for item in tools_schema
        ]
        normalized_items.sort()
        tools_normalized = "[" + ",".join(normalized_items) + "]"
        tools_hash = _short_hash(tools_normalized)

    # Exclude non-semantic fields from payload
    from core.llm.client import NON_SEMANTIC_FIELDS

    semantic_payload = {k: v for k, v in payload.items() if k not in NON_SEMANTIC_FIELDS}
    payload_normalized = json.dumps(semantic_payload, sort_keys=True, ensure_ascii=False)
    payload_hash = _short_hash(payload_normalized)

    return PrefixShape(
        system_hash=system_hash,
        tools_hash=tools_hash,
        payload_hash=payload_hash,
        call_point=call_point,
    )


def compare_shape(
    prev: PrefixShape | None,
    cur: PrefixShape,
    server_cache_hit: int = 0,
    server_cache_miss: int = 0,
) -> CacheDiagnostics:
    """Compare two prefix shapes and return diagnostics.

    Args:
        prev: Previous PrefixShape (None if first call).
        cur: Current PrefixShape.
        server_cache_hit: Server-side cache hit tokens.
        server_cache_miss: Server-side cache miss tokens.

    Returns:
        CacheDiagnostics with change detection results.
    """
    if prev is None:
        return CacheDiagnostics(
            prefix_hash=cur.prefix_hash,
            prefix_changed=False,
            change_reasons=[],
            server_cache_hit=server_cache_hit,
            server_cache_miss=server_cache_miss,
        )

    reasons: list[str] = []
    if prev.system_hash != cur.system_hash:
        reasons.append("system")
    if prev.tools_hash != cur.tools_hash:
        reasons.append("tools")
    if prev.payload_hash != cur.payload_hash:
        reasons.append("payload")

    return CacheDiagnostics(
        prefix_hash=cur.prefix_hash,
        prefix_changed=len(reasons) > 0,
        change_reasons=reasons,
        server_cache_hit=server_cache_hit,
        server_cache_miss=server_cache_miss,
    )


class PrefixHashTracker:
    """Tracks prefix shape stability per call_point.

    Maintains per-call_point history of PrefixShape and cache stats
    for diagnostics. Pure observability — does NOT influence cache
    read/write decisions.
    """

    def __init__(self) -> None:
        self._shapes: dict[str, PrefixShape] = {}
        self._last_diagnostics: dict[str, CacheDiagnostics] = {}
        self._cache_stats: dict[str, dict[str, int]] = {}

    def compute_prefix_hash(
        self,
        call_point: str,
        system_prompt: str,
        payload: dict[str, Any],
        tools_schema: list[dict[str, Any]] | None = None,
    ) -> tuple[str, bool, list[str]]:
        """Compute prefix hash and detect changes.

        Args:
            call_point: The call point identifier.
            system_prompt: System prompt string.
            payload: Request payload.
            tools_schema: Tools schema list.

        Returns:
            Tuple of (prefix_hash, changed, change_reasons).
        """
        cur_shape = capture_shape(
            call_point=call_point,
            payload=payload,
            system_prompt=system_prompt,
            tools_schema=tools_schema,
        )

        prev_shape = self._shapes.get(call_point)
        diagnostics = compare_shape(
            prev=prev_shape,
            cur=cur_shape,
            server_cache_hit=self._cache_stats.get(call_point, {}).get("hit", 0),
            server_cache_miss=self._cache_stats.get(call_point, {}).get("miss", 0),
        )

        # Update state
        self._shapes[call_point] = cur_shape
        self._last_diagnostics[call_point] = diagnostics

        return (cur_shape.prefix_hash, diagnostics.prefix_changed, diagnostics.change_reasons)

    def update_cache_stats(
        self,
        call_point: str,
        server_cache_hit: int = 0,
        server_cache_miss: int = 0,
    ) -> None:
        """Update cumulative cache stats for a call_point.

        Args:
            call_point: The call point identifier.
            server_cache_hit: Server-side cache hit tokens to add.
            server_cache_miss: Server-side cache miss tokens to add.
        """
        if call_point not in self._cache_stats:
            self._cache_stats[call_point] = {"hit": 0, "miss": 0}
        self._cache_stats[call_point]["hit"] += server_cache_hit
        self._cache_stats[call_point]["miss"] += server_cache_miss

    def get_diagnostics(self, call_point: str) -> CacheDiagnostics:
        """Get diagnostics for a specific call_point.

        Args:
            call_point: The call point identifier.

        Returns:
            CacheDiagnostics for the call_point. Returns empty
            diagnostics if call_point has no history.
        """
        if call_point in self._last_diagnostics:
            return self._last_diagnostics[call_point]
        return CacheDiagnostics(
            prefix_hash="",
            prefix_changed=False,
            change_reasons=[],
        )

    def get_session_stats(self) -> dict[str, Any]:
        """Get session-level aggregated cache stats.

        Returns:
            Dict with total_hits, total_misses, hit_rate.
        """
        total_hits = sum(s["hit"] for s in self._cache_stats.values())
        total_misses = sum(s["miss"] for s in self._cache_stats.values())
        total = total_hits + total_misses
        hit_rate = total_hits / total if total > 0 else 0.0

        return {
            "total_hits": total_hits,
            "total_misses": total_misses,
            "hit_rate": hit_rate,
        }
