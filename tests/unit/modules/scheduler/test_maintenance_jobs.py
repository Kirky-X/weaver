# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors


"""Regression tests for maintenance job error isolation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.scheduler.maintenance_jobs import MaintenanceJobs


class TestT008LowFixes:
    """Regression tests for LOW findings."""

    @pytest.mark.asyncio
    async def test_llm_failure_cleanup_error_returns_zero(self):
        """#268: a transient repo failure is isolated, not propagated."""
        repo = MagicMock()
        repo.cleanup_older_than = AsyncMock(side_effect=RuntimeError("boom"))
        jobs = MaintenanceJobs(
            relational_pool=MagicMock(),
            graph_writer=MagicMock(),
            pending_sync_repo=MagicMock(),
            llm_failure_repo=repo,
        )

        assert await jobs.llm_failure_cleanup() == 0
