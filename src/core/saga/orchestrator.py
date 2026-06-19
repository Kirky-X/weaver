# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Saga orchestrator for coordinating cross-database transactions.

Implements the central Saga Orchestrator pattern, managing saga lifecycle
(start, execute, compensate), step execution with logging, timeout
detection, and retry with exponential backoff.

Implements:
    - SagaOrchestrator: Coordinates saga lifecycle across PostgreSQL, Neo4j, Redis
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from core.observability import get_logger
from core.observability.metrics import metrics
from core.saga.alerts import SagaAlertService
from core.saga.executor import CompensationExecutor
from core.saga.repository import SagaLogRepo

log = get_logger(__name__)

# Default configuration
DEFAULT_SAGA_TIMEOUT_SECONDS = 300  # 5 minutes
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY_SECONDS = 60.0  # 1 minute (matches doc: 1min→4min→15min→60min)
DEFAULT_RETRY_MAX_DELAY_SECONDS = 3600.0  # 60 minutes


class SagaStatus(str, Enum):
    """Status of a saga instance."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass
class SagaStep:
    """Definition of a saga step.

    Attributes:
        name: Step name for logging and identification.
        execute: Async callable to execute the step.
        compensation_data: Serializable data for compensation if step succeeds.
    """

    name: str
    execute: Callable[[], Coroutine[Any, Any, Any]]
    compensation_data: dict[str, Any] | None = None


@dataclass
class SagaResult:
    """Result of a saga execution.

    Attributes:
        saga_id: ID of the saga.
        status: Final status of the saga.
        completed_steps: Names of steps that completed successfully.
        failed_step: Name of the step that failed (if any).
        error: Error message (if any).
        compensation_result: Result of compensation (if executed).
    """

    saga_id: uuid.UUID
    status: SagaStatus
    completed_steps: list[str] = field(default_factory=list)
    failed_step: str | None = None
    error: str | None = None
    compensation_result: Any = None


class SagaOrchestrator:
    """Orchestrates saga lifecycle for cross-database transactions.

    Coordinates the execution of saga steps, logs progress to the
    saga_logs table, handles failures with compensation, and supports
    timeout detection and retry with exponential backoff.

    Args:
        log_repo: Repository for saga log persistence.
        timeout_seconds: Maximum saga execution time.
        max_retries: Maximum retry attempts per step.
        retry_base_delay: Base delay for exponential backoff.
        retry_max_delay: Maximum delay for exponential backoff.
    """

    def __init__(
        self,
        log_repo: SagaLogRepo,
        timeout_seconds: int = DEFAULT_SAGA_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY_SECONDS,
        retry_max_delay: float = DEFAULT_RETRY_MAX_DELAY_SECONDS,
        alert_service: SagaAlertService | None = None,
    ) -> None:
        self._log_repo = log_repo
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay
        self._compensation_executor = CompensationExecutor()
        self._alert_service = alert_service or SagaAlertService()

    async def start_saga(
        self,
        article_id: uuid.UUID,
        steps: list[SagaStep],
    ) -> SagaResult:
        """Start and execute a new saga.

        Args:
            article_id: ID of the article being processed.
            steps: Ordered list of saga steps to execute.

        Returns:
            SagaResult with final status and details.
        """
        saga_id = uuid.uuid4()
        metrics.saga_active_count.inc()
        log.info(
            "saga_started",
            saga_id=str(saga_id),
            article_id=str(article_id),
            step_count=len(steps),
        )

        result = await self._execute_saga(saga_id, article_id, steps)

        metrics.saga_active_count.dec()
        metrics.saga_total.labels(status=result.status.value).inc()
        log.info(
            "saga_finished",
            saga_id=str(saga_id),
            status=result.status.value,
            completed_steps=len(result.completed_steps),
        )
        return result

    async def _execute_saga(
        self,
        saga_id: uuid.UUID,
        article_id: uuid.UUID,
        steps: list[SagaStep],
    ) -> SagaResult:
        """Execute saga steps with timeout and compensation on failure."""
        completed_steps: list[str] = []
        completed_compensation_data: list[dict[str, Any]] = []

        try:
            async with asyncio.timeout(self._timeout_seconds):
                for step in steps:
                    step_result = await self._execute_step_with_retry(saga_id, article_id, step)

                    if step_result is None:
                        # Step succeeded
                        completed_steps.append(step.name)
                        if step.compensation_data:
                            completed_compensation_data.append(step.compensation_data)
                    else:
                        # Step failed after retries
                        return await self._handle_step_failure(
                            saga_id,
                            article_id,
                            step.name,
                            step_result,
                            completed_compensation_data,
                        )

                # All steps succeeded
                return SagaResult(
                    saga_id=saga_id,
                    status=SagaStatus.COMPLETED,
                    completed_steps=completed_steps,
                )

        except TimeoutError:
            log.error(
                "saga_timed_out",
                saga_id=str(saga_id),
                timeout=self._timeout_seconds,
            )
            # Alert on timeout
            await self._alert_service.alert_saga_timeout(
                saga_id=str(saga_id),
                article_id=str(article_id),
                timeout_seconds=self._timeout_seconds,
            )
            # Compensate completed steps
            comp_result = await self._compensation_executor.execute_compensations(
                completed_compensation_data
            )
            return SagaResult(
                saga_id=saga_id,
                status=SagaStatus.TIMED_OUT,
                completed_steps=completed_steps,
                error=f"Saga timed out after {self._timeout_seconds}s",
                compensation_result=comp_result,
            )

    async def _execute_step_with_retry(
        self,
        saga_id: uuid.UUID,
        article_id: uuid.UUID,
        step: SagaStep,
    ) -> str | None:
        """Execute a step with retry and exponential backoff.

        Args:
            saga_id: ID of the saga.
            article_id: ID of the article.
            step: Step to execute.

        Returns:
            Error message if step failed after all retries, None if succeeded.
        """
        log_id = await self._log_repo.create(
            saga_id=saga_id,
            article_id=article_id,
            step_name=step.name,
            step_status="started",
            compensation_data=step.compensation_data,
        )

        last_error: str | None = None

        for attempt in range(self._max_retries + 1):
            try:
                step_start = datetime.now(UTC)
                await step.execute()
                step_duration = (datetime.now(UTC) - step_start).total_seconds()
                metrics.saga_step_latency.labels(step_name=step.name).observe(step_duration)
                await self._log_repo.update_status(log_id, "completed")
                log.info(
                    "saga_step_completed",
                    saga_id=str(saga_id),
                    step_name=step.name,
                    attempt=attempt,
                )
                return None  # Success

            except Exception as exc:
                last_error = str(exc)
                log.warning(
                    "saga_step_failed_attempt",
                    saga_id=str(saga_id),
                    step_name=step.name,
                    attempt=attempt,
                    error=last_error,
                )

                if attempt < self._max_retries:
                    await self._log_repo.increment_retry(log_id)
                    delay = min(
                        self._retry_base_delay * (2**attempt),
                        self._retry_max_delay,
                    )
                    await asyncio.sleep(delay)

        # All retries exhausted
        await self._log_repo.update_status(log_id, "failed", error_message=last_error)
        return last_error

    async def _handle_step_failure(
        self,
        saga_id: uuid.UUID,
        article_id: uuid.UUID,
        failed_step: str,
        error: str,
        completed_compensation_data: list[dict[str, Any]],
    ) -> SagaResult:
        """Handle step failure by executing compensations.

        Args:
            saga_id: ID of the saga.
            article_id: ID of the article.
            failed_step: Name of the failed step.
            error: Error message from the failed step.
            completed_compensation_data: Compensation data for completed steps.

        Returns:
            SagaResult with compensation details.
        """
        log.info(
            "saga_step_failure_initiating_compensation",
            saga_id=str(saga_id),
            failed_step=failed_step,
            compensation_count=len(completed_compensation_data),
        )

        comp_result = await self._compensation_executor.execute_compensations(
            completed_compensation_data
        )

        if comp_result.success:
            status = SagaStatus.COMPENSATED
        else:
            status = SagaStatus.FAILED
            # Alert on saga failure (compensation also failed)
            await self._alert_service.alert_saga_failure(
                saga_id=str(saga_id),
                article_id=str(article_id),
                failed_step=failed_step,
                error=error,
            )
            # Alert on compensation failures
            for failed in comp_result.failed_steps:
                await self._alert_service.alert_compensation_failure(
                    saga_id=str(saga_id),
                    failed_step=failed["step_name"],
                    error=failed["error"],
                )

        return SagaResult(
            saga_id=saga_id,
            status=status,
            failed_step=failed_step,
            error=error,
            compensation_result=comp_result,
        )

    async def compensate_saga(self, saga_id: uuid.UUID) -> SagaResult:
        """Manually trigger compensation for a saga.

        Used for manual intervention when automatic compensation fails.

        Args:
            saga_id: ID of the saga to compensate.

        Returns:
            SagaResult with compensation details.
        """
        log.info("manual_compensation_started", saga_id=str(saga_id))

        compensation_data = await self._log_repo.get_completed_compensation_data(saga_id)

        if not compensation_data:
            return SagaResult(
                saga_id=saga_id,
                status=SagaStatus.COMPENSATED,
                error="No completed steps to compensate",
            )

        comp_result = await self._compensation_executor.execute_compensations(compensation_data)

        status = SagaStatus.COMPENSATED if comp_result.success else SagaStatus.FAILED

        return SagaResult(
            saga_id=saga_id,
            status=status,
            compensation_result=comp_result,
        )

    async def retry_saga(
        self,
        article_id: uuid.UUID,
        steps: list[SagaStep],
    ) -> SagaResult:
        """Retry a failed saga from the beginning.

        Creates a new saga instance and re-executes all steps.

        Args:
            article_id: ID of the article.
            steps: Steps to re-execute.

        Returns:
            SagaResult for the new saga attempt.
        """
        return await self.start_saga(article_id, steps)

    async def get_saga_status(self, saga_id: uuid.UUID) -> dict[str, Any]:
        """Get the status of a saga by querying its logs.

        Args:
            saga_id: ID of the saga.

        Returns:
            Dict with saga status information.
        """
        logs = await self._log_repo.get_by_saga_id(saga_id)

        if not logs:
            return {"saga_id": str(saga_id), "status": "unknown", "steps": []}

        steps = []
        for entry in logs:
            steps.append(
                {
                    "step_name": entry.step_name,
                    "step_status": entry.step_status,
                    "started_at": entry.started_at.isoformat() if entry.started_at else None,
                    "completed_at": entry.completed_at.isoformat() if entry.completed_at else None,
                    "error_message": entry.error_message,
                    "retry_count": entry.retry_count,
                }
            )

        # Determine overall status from step statuses
        step_statuses = {s["step_status"] for s in steps}
        if "failed" in step_statuses:
            overall_status = "failed"
        elif all(s == "completed" for s in step_statuses):
            overall_status = "completed"
        else:
            overall_status = "running"

        return {
            "saga_id": str(saga_id),
            "status": overall_status,
            "steps": steps,
        }

    async def get_saga_logs(self, saga_id: uuid.UUID) -> list[Any]:
        """Get saga logs by saga ID.

        Args:
            saga_id: ID of the saga.

        Returns:
            List of SagaLog entries for the saga.
        """
        return await self._log_repo.get_by_saga_id(saga_id)

    async def get_saga_logs_by_article(self, article_id: uuid.UUID) -> list[Any]:
        """Get saga logs by article ID.

        Args:
            article_id: Article UUID.

        Returns:
            List of SagaLog entries for the article.
        """
        return await self._log_repo.get_by_article_id(article_id)

    async def get_failed_saga_logs(self, limit: int = 100) -> list[Any]:
        """Get failed saga logs.

        Args:
            limit: Maximum number of logs to return.

        Returns:
            List of failed SagaLog entries.
        """
        return await self._log_repo.get_failed_logs(limit=limit)
