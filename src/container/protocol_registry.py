# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Protocol → implementation binding registry.

The single source of truth for runtime contract validation: at startup the
container validates every registered binding via ``assert_implements`` so a
signature drift fails fast instead of surfacing as a confusing request-time
error. Protocols defined in ``core.protocols`` but absent from the registry
produce a startup WARNING — new bindings must be registered here.
"""

from __future__ import annotations

from typing import Any

from core.observability import get_logger
from core.protocols import (
    ArticleRepository,
    BingSearchProtocol,
    CachePool,
    DeduplicationStrategy,
    EntityRepository,
    GraphPool,
    GraphWriter,
    KnowledgeCacheProtocol,
    PipelineService,
    RelationalPool,
    SentimentTrendProtocol,
    SourceAuthorityRepository,
    TaskRegistryService,
    TrendDetectionProtocol,
    VectorRepository,
    assert_implements,
)

log = get_logger(__name__)

# (Protocol, container accessor name). Accessors may return None when an
# optional backend is absent (e.g. graph_pool under the DuckDB strategy);
# None bindings are skipped rather than treated as mismatches.
PROTOCOL_BINDINGS: list[tuple[type, str]] = [
    # ── Pool protocols ────────────────────────────────────────────
    (RelationalPool, "relational_pool"),
    (GraphPool, "graph_pool"),
    (CachePool, "cache_client"),
    # ── Repository protocols ──────────────────────────────────────
    (ArticleRepository, "article_repo"),
    (VectorRepository, "vector_repo"),
    (EntityRepository, "graph_entity_repo"),
    (GraphWriter, "graph_writer"),
    (SourceAuthorityRepository, "source_authority_repo"),
    # ── Service protocols ─────────────────────────────────────────
    (PipelineService, "pipeline_service"),
    (TaskRegistryService, "task_registry"),
    (DeduplicationStrategy, "deduplicator"),
    (SentimentTrendProtocol, "sentiment_trend_analyzer"),
    (TrendDetectionProtocol, "trend_detector"),
    # ── Web search / cache protocols ──────────────────────────────
    (BingSearchProtocol, "bing_searcher"),
    (KnowledgeCacheProtocol, "knowledge_cache"),
]

# Protocol classes known to core.protocols but intentionally unvalidated here
# (container-side facades, dataclass-ish view protocols, optional backends).
KNOWN_UNREGISTERED = {
    # Constructed lazily in endpoint/service code, not managed by container
    "AnalyticsStorageProtocol",
    "DailyBriefingProtocol",
    "EmbeddingServiceProtocol",
    "GraphArticleRepository",
    "MapperProtocol",
    "QueryExpanderProtocol",
}


def all_defined_protocols() -> set[str]:
    """Names of every Protocol class exported by core.protocols."""
    from core import protocols as protocols_pkg

    names: set[str] = set()
    for name in dir(protocols_pkg):
        obj = getattr(protocols_pkg, name)
        if isinstance(obj, type) and getattr(obj, "_is_protocol", False):
            names.add(name)
    return names


def validate_protocol_bindings(container: Any) -> list[str]:
    """Validate every registered binding; return unregistered protocol names.

    Raises:
        AssertionError: if a bound implementation does not satisfy its protocol.

    """
    problems: list[str] = []
    for protocol, accessor in PROTOCOL_BINDINGS:
        if not hasattr(container, accessor):
            problems.append(f"{protocol.__name__}: container has no accessor '{accessor}'")
            continue
        try:
            impl = getattr(container, accessor)()
        except Exception as exc:
            log.debug(
                "protocol_binding_skipped",
                protocol=protocol.__name__,
                accessor=accessor,
                error=str(exc),
            )
            continue
        if impl is None:
            continue
        try:
            assert_implements(impl, protocol)
        except (TypeError, ValueError) as exc:
            problems.append(f"{protocol.__name__} <- {accessor}(): {exc}")

    if problems:
        raise AssertionError(
            "Protocol contract validation failed:\n" + "\n".join(f"- {p}" for p in problems)
        )

    unregistered = (
        all_defined_protocols()
        - {protocol.__name__ for protocol, _ in PROTOCOL_BINDINGS}
        - KNOWN_UNREGISTERED
    )
    if unregistered:
        log.warning(
            "unregistered_protocols",
            protocols=sorted(unregistered),
            hint="register new protocols in container/protocol_registry.py",
        )
    return sorted(unregistered)
