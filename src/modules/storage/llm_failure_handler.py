# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Event handler for LLM failure events — writes to PostgreSQL."""

from __future__ import annotations

from core.event.bus import LLMFailureEvent
from core.observability.logging import get_logger

log = get_logger("llm_failure_handler")


async def handle_llm_failure(event: LLMFailureEvent) -> None:
    """Handle LLMFailureEvent by recording it to PostgreSQL.

    This handler is registered on the shared EventBus. Errors are logged
    but MUST NOT propagate — per EventBus error-isolation contract.

    Args:
        event: The LLM failure event published by LLMQueueManager.
    """
    from container import get_container
    from modules.storage.llm_failure_repo import LLMFailureRepo

    try:
        container = get_container()
        repo: LLMFailureRepo = container._llm_failure_repo
    except Exception as exc:
        log.warning("llm_failure_handler_no_repo", error=str(exc))
        return

    try:
        await repo.record(event)
    except Exception as exc:
        log.error(
            "llm_failure_handler_error",
            call_point=event.call_point,
            error=str(exc),
        )
