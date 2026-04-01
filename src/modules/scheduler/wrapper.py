# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified decorator for APScheduler tasks: timeout, logging, metrics."""

from __future__ import annotations

import asyncio
import functools
import time

from core.observability.logging import get_logger
from core.observability.metrics import metrics

log = get_logger("scheduler_task")


def scheduled_task(job_id: str, timeout_seconds: int = 600):
    """Decorator for APScheduler job methods.

    Provides:
    - Structured start/complete/error logging
    - asyncio.wait_for timeout protection
    - Prometheus duration histogram and execution counter
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.monotonic()
            log.info(f"{job_id}_start")
            metrics.scheduler_job_total.labels(job=job_id, status="started").inc()

            try:
                result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout_seconds)
                duration = time.monotonic() - start
                log.info(
                    f"{job_id}_complete",
                    duration_seconds=round(duration, 2),
                )
                metrics.scheduler_job_duration.labels(job=job_id, status="success").observe(
                    duration
                )
                metrics.scheduler_job_total.labels(job=job_id, status="success").inc()
                return result

            except TimeoutError:
                duration = time.monotonic() - start
                log.error(
                    f"{job_id}_timeout",
                    timeout_seconds=timeout_seconds,
                    duration_seconds=round(duration, 2),
                )
                metrics.scheduler_job_duration.labels(job=job_id, status="timeout").observe(
                    duration
                )
                metrics.scheduler_job_total.labels(job=job_id, status="timeout").inc()
                return 0

            except Exception as exc:
                duration = time.monotonic() - start
                log.error(
                    f"{job_id}_error",
                    error=str(exc),
                    duration_seconds=round(duration, 2),
                )
                metrics.scheduler_job_duration.labels(job=job_id, status="error").observe(duration)
                metrics.scheduler_job_total.labels(job=job_id, status="error").inc()
                return 0

        return wrapper

    return decorator
