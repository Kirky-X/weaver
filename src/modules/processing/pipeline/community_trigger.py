# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Community update trigger collaborator.

Inspects freshly persisted pipeline states and, when enough new entities have
accumulated, fires a non-blocking incremental community update.

Extracted from ``Pipeline`` to keep the orchestrator focused on flow control.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from core.observability import get_logger
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from modules.knowledge.graph.community.updater import IncrementalCommunityUpdater

log = get_logger(__name__)


class CommunityUpdateTrigger:
    """Trigger incremental community updates after persistence.

    Single responsibility: extract entity names from processed states, check
    whether the incremental community updater should run, and either fire it
    asynchronously (fire-and-forget) or bump the pending counter.

    Args:
        community_updater: Incremental community updater. May be None when
            community detection is disabled.
    """

    def __init__(self, *, community_updater: IncrementalCommunityUpdater | None) -> None:
        self._community_updater = community_updater

    async def maybe_trigger(self, states: list[PipelineState]) -> None:
        """Check and trigger incremental community update after Phase 4 persist.

        This is non-blocking and logs the update status without affecting
        pipeline completion.

        Args:
            states: Pipeline states after persist.
        """
        if not self._community_updater:
            return

        # Extract entity names from processed states
        entity_names: list[str] = []
        for state in states:
            if state.get("entities"):
                entities = state["entities"]
                if isinstance(entities, list):
                    for entity in entities:
                        if isinstance(entity, dict):
                            name = entity.get("canonical_name") or entity.get("name")
                            if name:
                                entity_names.append(name)
                        elif hasattr(entity, "canonical_name"):
                            entity_names.append(entity.canonical_name)
                        elif hasattr(entity, "name"):
                            entity_names.append(entity.name)

        if not entity_names:
            log.debug("community_update_skip_no_entities")
            return

        try:
            # Get current stats to check trigger conditions
            stats = await self._community_updater.get_stats()
            pending_count = stats.pending_entity_count + len(entity_names)

            # Check if update should be triggered
            if await self._community_updater.should_trigger(
                pending_count, stats.last_incremental_update_at
            ):
                log.info(
                    "community_update_triggered",
                    entity_count=len(entity_names),
                    pending_total=pending_count,
                )
                # Run update asynchronously (fire and forget) — non-blocking
                task = asyncio.create_task(
                    self._community_updater.run_incremental_update(entity_names)
                )

                def _on_community_update_done(t: asyncio.Task[object]) -> None:
                    """Log result or error from background community update."""
                    try:
                        result = t.result()
                        log.info(
                            "community_update_complete",
                            affected=getattr(result, "affected_communities", None),
                            reassigned=getattr(result, "entities_reassigned", None),
                            duration=getattr(result, "duration_seconds", None),
                        )
                    except Exception as exc:
                        log.warning(
                            "community_update_background_failed",
                            error=str(exc),
                            error_type=type(exc).__name__,
                        )

                task.add_done_callback(_on_community_update_done)
            else:
                # Increment pending count for next time
                await self._community_updater.increment_pending_count(len(entity_names))
                log.debug(
                    "community_update_pending",
                    added=len(entity_names),
                    pending_total=pending_count,
                )

        except Exception as exc:
            # Don't fail pipeline if community update fails
            log.warning(
                "community_update_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
