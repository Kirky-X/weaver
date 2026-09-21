# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Redis distributed lock for scheduled jobs.

Multi-replica deployments must not let every replica fire the same
``APScheduler`` task. The lock uses ``SET key value NX EX ttl``: the first
replica to grab it runs the job, the others skip (DEBUG-logged). Locks are
released only by their holder; the TTL bounds the damage of a crashed
holder.

When the cache pool lacks ``set_nx`` (in-memory degraded mode) or no pool
is available, the job runs unprotected with a WARNING — correct for
single-instance deployments, where skipping would be a false positive.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, TypeVar, cast

from core.observability import get_logger

log = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])

# Cap for lock TTLs derived from job intervals (1 hour)
DEFAULT_LOCK_TTL_CAP = 3600


# Atomic compare-and-delete: only removes the key when the holder matches.
_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)


async def _release_lock(cache_pool: Any, name: str, holder_id: str) -> None:
    """Release the lock only if still held by holder_id (atomic when possible)."""
    eval_fn = getattr(cache_pool, "eval", None)
    if eval_fn is not None:
        try:
            await eval_fn(_RELEASE_LUA, 1, name, holder_id)
            return
        except Exception as exc:
            log.debug("distributed_lock_lua_release_failed", lock=name, error=str(exc))
    # Non-atomic fallback for pools without eval (single-instance semantics).
    try:
        holder = await cache_pool.get(name)
        if holder == holder_id:
            await cache_pool.delete(name)
    except Exception as exc:
        log.debug("distributed_lock_fallback_release_failed", lock=name, error=str(exc))


def distributed_lock(
    name: str,
    ttl_seconds: int = DEFAULT_LOCK_TTL_CAP,
    cache_pool: Any = None,
    instance_id: str | None = None,
) -> Callable[[F], F]:
    """Decorate an async job so only one replica runs it per TTL window.

    Args:
        name: Lock key (convention: ``weaver:scheduler:<job_id>``).
        ttl_seconds: Lock expiry; must outlive the job's expected runtime.
        cache_pool: Cache pool exposing ``set_nx``/``get``/``delete``.
        instance_id: Holder identity; defaults to a per-decoration UUID.
    """
    holder_id = instance_id or uuid.uuid4().hex

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            set_nx = getattr(cache_pool, "set_nx", None)
            if set_nx is None:
                log.warning(
                    "distributed_lock_unavailable",
                    lock=name,
                    hint="running without multi-instance protection (single-instance OK)",
                )
                return await func(*args, **kwargs)

            acquired = await set_nx(name, holder_id, ex=ttl_seconds)
            if not acquired:
                log.debug("distributed_lock_held_elsewhere", lock=name)
                return None
            try:
                return await func(*args, **kwargs)
            finally:
                await _release_lock(cache_pool, name, holder_id)

        return cast(F, wrapper)

    return decorator


def trigger_interval_seconds(trigger: Any) -> float | None:
    """Return the trigger's interval in seconds, or None for cron/date triggers."""
    interval = getattr(trigger, "interval", None)
    if isinstance(interval, timedelta):
        return interval.total_seconds()
    return None


def wrap_scheduler_with_lock(
    scheduler: Any,
    cache_pool: Any,
    ttl_cap: int = DEFAULT_LOCK_TTL_CAP,
) -> None:
    """Intercept ``scheduler.add_job`` so every registered job holds the lock.

    TTL is ``min(interval * 0.8, ttl_cap)`` for interval jobs and ``ttl_cap``
    for cron/date jobs. Must be called before any ``add_job`` calls.
    """
    original_add_job = scheduler.add_job

    def add_job_with_lock(func: Any, trigger: Any = None, *args: Any, **kwargs: Any) -> Any:
        job_id = kwargs.get("id") or getattr(func, "__name__", None) or f"job_{id(func):x}"
        interval = trigger_interval_seconds(trigger)
        # Floor at 1s: sub-1.25s intervals would otherwise truncate to ttl=0,
        # making the lock expire immediately.
        ttl = max(1, min(int(interval * 0.8), ttl_cap)) if interval else ttl_cap
        locked = distributed_lock(
            f"weaver:scheduler:{job_id}", ttl_seconds=ttl, cache_pool=cache_pool
        )(func)
        return original_add_job(locked, trigger, *args, **kwargs)

    scheduler.add_job = add_job_with_lock
