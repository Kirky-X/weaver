# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Independent daemon thread for 3-day rolling cleanup of LLM failure records."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

from core.observability.logging import get_logger

if TYPE_CHECKING:
    from modules.storage.llm_failure_repo import LLMFailureRepo

log = get_logger("llm_failure_cleanup")


class LLMFailureCleanupThread:
    """Daemon thread that purges LLM failure records older than 3 days.

    Runs immediately on start (closing the startup vacuum gap), then every
    24 hours. Thread-safe: creates its own asyncio event loop.
    """

    def __init__(self, repo: LLMFailureRepo) -> None:
        self._repo = repo
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the cleanup thread. Runs cleanup once immediately, then loops."""
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="llm-failure-cleanup",
        )
        self._thread.start()
        log.info("llm_failure_cleanup_thread_started")

    def _run(self) -> None:
        """Thread target: own event loop, run cleanup immediately then every 24h."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Immediate cleanup on startup
            self._execute_cleanup(loop)
            # Then loop: sleep 24h between runs
            while not self._stop_event.wait(86400):
                # Each iteration gets a fresh loop to avoid loop-state corruption
                # if the postgres pool was closed by container.shutdown().
                loop.close()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._execute_cleanup(loop)
        finally:
            loop.close()
            log.info("llm_failure_cleanup_thread_stopped")

    def _execute_cleanup(self, loop: asyncio.AbstractEventLoop) -> None:
        """Run one cleanup cycle on the given loop, catching loop/pool errors."""
        try:
            loop.run_until_complete(self._repo.cleanup_older_than(3))
        except RuntimeError as e:
            # Raised when the loop is already closed (container shut down mid-sleep).
            log.debug("llm_failure_cleanup_loop_closed", error=str(e))
        except Exception as e:
            # Raised when asyncpg connection is already closed (pool shut down).
            log.warning("llm_failure_cleanup_error", error=str(e))

    def stop(self) -> None:
        """Signal the thread to stop and wait for it to terminate."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
