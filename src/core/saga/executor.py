# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Compensation executor for Saga rollback operations.

Executes compensation commands in reverse order when a saga step fails.
Handles partial compensation failures, timeouts, and idempotency.

Implements:
    - CompensationExecutor: Execute compensations in reverse order
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from core.observability import get_logger
from core.observability.metrics import metrics
from core.saga.compensation import (
    deserialize_compensation,
)

log = get_logger(__name__)

# Default timeout for a single compensation operation
DEFAULT_COMPENSATION_TIMEOUT_SECONDS = 120  # 2 minutes


@dataclass
class CompensationResult:
    """Result of a compensation execution.

    Attributes:
        success: Whether all compensations completed successfully.
        completed_steps: Names of steps that were compensated.
        failed_steps: Names of steps that failed compensation with error details.
    """

    success: bool
    completed_steps: list[str] = field(default_factory=list)
    failed_steps: list[dict[str, str]] = field(default_factory=list)


class CompensationExecutor:
    """Executor for saga compensation transactions.

    Executes compensation commands in reverse order (last completed step first).
    Handles partial failures by continuing with remaining compensations and
    reporting all failures.

    Args:
        timeout_seconds: Timeout for each individual compensation operation.
    """

    def __init__(self, timeout_seconds: int = DEFAULT_COMPENSATION_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    async def execute_compensations(
        self,
        compensation_data_list: list[dict[str, Any]],
    ) -> CompensationResult:
        """Execute compensation commands in reverse order.

        Args:
            compensation_data_list: List of serialized compensation data dicts,
                ordered by step execution time (oldest first). Will be reversed
                for compensation execution.

        Returns:
            CompensationResult with success status and details.
        """
        if not compensation_data_list:
            return CompensationResult(success=True)

        # Reverse order: compensate last completed step first
        reversed_compensations = list(reversed(compensation_data_list))

        completed_steps: list[str] = []
        failed_steps: list[dict[str, str]] = []

        for comp_data in reversed_compensations:
            step_name = comp_data.get("step_name", "unknown")
            try:
                command = deserialize_compensation(comp_data)
                await asyncio.wait_for(
                    command.execute(),
                    timeout=self._timeout_seconds,
                )
                completed_steps.append(step_name)
                metrics.saga_compensation_total.labels(step_name=step_name, status="success").inc()
                log.info(
                    "compensation_step_completed",
                    step_name=step_name,
                )
            except TimeoutError:
                error_msg = f"Compensation timed out after {self._timeout_seconds}s"
                failed_steps.append({"step_name": step_name, "error": error_msg})
                metrics.saga_compensation_total.labels(step_name=step_name, status="failure").inc()
                log.error(
                    "compensation_step_timeout",
                    step_name=step_name,
                    timeout=self._timeout_seconds,
                )
            except Exception as exc:
                error_msg = str(exc)
                failed_steps.append({"step_name": step_name, "error": error_msg})
                metrics.saga_compensation_total.labels(step_name=step_name, status="failure").inc()
                log.error(
                    "compensation_step_failed",
                    step_name=step_name,
                    error=error_msg,
                    exc_info=True,
                )

        success = len(failed_steps) == 0
        result = CompensationResult(
            success=success,
            completed_steps=completed_steps,
            failed_steps=failed_steps,
        )

        log.info(
            "compensation_execution_completed",
            success=success,
            completed_count=len(completed_steps),
            failed_count=len(failed_steps),
        )

        return result

    async def execute_single_compensation(
        self,
        compensation_data: dict[str, Any],
    ) -> bool:
        """Execute a single compensation command.

        Args:
            compensation_data: Serialized compensation data dict.

        Returns:
            True if compensation succeeded, False otherwise.
        """
        step_name = compensation_data.get("step_name", "unknown")
        try:
            command = deserialize_compensation(compensation_data)
            await asyncio.wait_for(
                command.execute(),
                timeout=self._timeout_seconds,
            )
            log.info("single_compensation_completed", step_name=step_name)
            return True
        except TimeoutError:
            log.error(
                "single_compensation_timeout",
                step_name=step_name,
                timeout=self._timeout_seconds,
            )
            return False
        except Exception as exc:
            log.error(
                "single_compensation_failed",
                step_name=step_name,
                error=str(exc),
                exc_info=True,
            )
            return False
