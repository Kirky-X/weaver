# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unified decorator for APScheduler tasks: timeout, logging, metrics."""

from __future__ import annotations

import asyncio
import functools
import time

from opentelemetry import trace

from core.observability import clear_task_context, get_logger, set_task_context
from core.observability.metrics import metrics

log = get_logger(__name__)

tracer = trace.get_tracer("scheduler")


def scheduled_task(job_id: str, timeout_seconds: int = 600):
    """Decorator for APScheduler job methods.

    Provides:
    - Structured start/complete/error logging
    - asyncio.wait_for timeout protection
    - Prometheus duration histogram and execution counter
    - OpenTelemetry trace context for meaningful trace_id in logs
    - Task context for meaningful req identifier in logs

    Returns:
        -1 on timeout, -2 on error, otherwise the wrapped function's return value.
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Set task context for log filter to use
            set_task_context(job_id, "scheduler")

            # Create OpenTelemetry span for trace context
            with tracer.start_as_current_span(f"scheduler.{job_id}") as span:
                span.set_attribute("job_id", job_id)
                span.set_attribute("timeout_seconds", timeout_seconds)

                start = time.monotonic()
                log.info("scheduler_task_start", job_id=job_id)
                metrics.scheduler_job_total.labels(job=job_id, status="started").inc()

                try:
                    result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout_seconds)
                    duration = time.monotonic() - start
                    log.info(
                        "scheduler_task_complete",
                        job_id=job_id,
                        duration_seconds=round(duration, 2),
                    )
                    metrics.scheduler_job_duration.labels(job=job_id, status="success").observe(
                        duration
                    )
                    metrics.scheduler_job_total.labels(job=job_id, status="success").inc()
                    span.set_attribute("success", True)
                    span.set_attribute("duration_seconds", duration)
                    return result

                except TimeoutError:
                    duration = time.monotonic() - start
                    log.error(
                        "scheduler_task_timeout",
                        job_id=job_id,
                        timeout_seconds=timeout_seconds,
                        duration_seconds=round(duration, 2),
                    )
                    metrics.scheduler_job_duration.labels(job=job_id, status="timeout").observe(
                        duration
                    )
                    metrics.scheduler_job_total.labels(job=job_id, status="timeout").inc()
                    span.set_attribute("success", False)
                    span.set_attribute("error", "timeout")
                    span.record_exception(Exception("Timeout"))
                    return -1

                except asyncio.CancelledError:
                    duration = time.monotonic() - start
                    log.info(
                        "scheduler_task_cancelled",
                        job_id=job_id,
                        duration_seconds=round(duration, 2),
                    )
                    span.set_attribute("success", False)
                    span.set_attribute("error", "cancelled")
                    return -2

                except Exception as exc:
                    duration = time.monotonic() - start
                    log.error(
                        "scheduler_task_error",
                        job_id=job_id,
                        error=str(exc),
                        duration_seconds=round(duration, 2),
                    )
                    metrics.scheduler_job_duration.labels(job=job_id, status="error").observe(
                        duration
                    )
                    metrics.scheduler_job_total.labels(job=job_id, status="error").inc()
                    span.set_attribute("success", False)
                    span.set_attribute("error", str(exc))
                    span.record_exception(exc)
                    return -2

                finally:
                    clear_task_context()

        return wrapper

    return decorator
