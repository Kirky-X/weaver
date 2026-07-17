# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for daily briefing scheduler job (T010 / R-briefing-006).

Covers:
- AnalyticsJobs.generate_daily_briefing generates 4 categories (general/finance/tech/ai)
- Error isolation: single category failure doesn't block others
- Service unavailable (LLM/pool missing) returns error dict, doesn't raise
- Cron registration in lifecycle._setup_scheduler: hour=8, minute=0,
  Asia/Shanghai, job name mentions "4 categories" (spec R-briefing-006)

The cron registration test uses source inspection (``inspect.getsource``)
because ``_setup_scheduler`` requires a full container to invoke. Source
inspection directly verifies spec R-briefing-006 (`0 8 * * *` Asia/Shanghai)
and acts as a regression guard.
"""

from __future__ import annotations

import inspect
import re
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.scheduler.analytics_jobs import AnalyticsJobs


def _make_analytics_jobs() -> AnalyticsJobs:
    """Build an AnalyticsJobs instance with mocked dependencies."""
    return AnalyticsJobs(
        relational_pool=MagicMock(),
        cache=MagicMock(),
    )


def _make_mock_briefing_result(*, category: str = "general", briefing_id: int = 1):
    """Build a mock BriefingResult-like object."""
    mock = MagicMock()
    mock.category = category
    mock.briefing_id = briefing_id
    mock.summary = f"Summary for {category}"
    mock.items = [{"rank": 1}]
    mock.narrative_mode = False
    return mock


class TestGenerateDailyBriefingJob:
    """Tests for AnalyticsJobs.generate_daily_briefing (T010)."""

    @pytest.mark.asyncio
    async def test_generates_4_categories(self) -> None:
        """generate_daily_briefing calls service.generate_briefing for all 4 categories."""
        jobs = _make_analytics_jobs()
        mock_service = MagicMock()
        mock_service.generate_briefing = AsyncMock(
            side_effect=lambda date, category: _make_mock_briefing_result(category=category)
        )

        with patch.object(jobs, "_build_briefing_service", return_value=mock_service):
            result = await jobs.generate_daily_briefing()

        # Verify all 4 categories were generated.
        expected_categories = {"general", "finance", "tech", "ai"}
        actual_categories = {
            call.kwargs["category"] for call in mock_service.generate_briefing.call_args_list
        }
        assert actual_categories == expected_categories
        assert mock_service.generate_briefing.call_count == 4
        # Result structure.
        assert result["categories_total"] == 4
        assert result["categories_generated"] == 4

    @pytest.mark.asyncio
    async def test_error_isolation_single_category_failure(self) -> None:
        """One category failing does NOT block other categories (Rule 12 + R-briefing-006)."""
        jobs = _make_analytics_jobs()
        mock_service = MagicMock()

        async def _generate(*, date, category):
            if category == "finance":
                raise RuntimeError("LLM timeout for finance")
            return _make_mock_briefing_result(category=category)

        mock_service.generate_briefing = AsyncMock(side_effect=_generate)

        with patch.object(jobs, "_build_briefing_service", return_value=mock_service):
            result = await jobs.generate_daily_briefing()

        # 3 succeeded, 1 failed.
        assert result["categories_generated"] == 3
        assert result["categories_total"] == 4
        # finance has error, others have briefing_id.
        assert "error" in result["results"]["finance"]
        assert "briefing_id" in result["results"]["general"]
        assert "briefing_id" in result["results"]["tech"]
        assert "briefing_id" in result["results"]["ai"]
        # All 4 categories were attempted (no short-circuit).
        assert mock_service.generate_briefing.call_count == 4

    @pytest.mark.asyncio
    async def test_service_unavailable_returns_error_not_raise(self) -> None:
        """When _build_briefing_service returns None, job returns error dict, doesn't raise.

        Scheduler must not be blocked by missing LLM/pool dependencies
        (R-briefing-006: failure logs error, doesn't block next execution).
        """
        jobs = _make_analytics_jobs()

        with patch.object(jobs, "_build_briefing_service", return_value=None):
            result = await jobs.generate_daily_briefing()

        assert "error" in result
        assert result["categories_generated"] == 0

    @pytest.mark.asyncio
    async def test_uses_today_date(self) -> None:
        """generate_daily_briefing uses date.today() for all categories."""
        jobs = _make_analytics_jobs()
        mock_service = MagicMock()
        mock_service.generate_briefing = AsyncMock(return_value=_make_mock_briefing_result())

        with patch.object(jobs, "_build_briefing_service", return_value=mock_service):
            await jobs.generate_daily_briefing()

        today = date.today()
        for call in mock_service.generate_briefing.call_args_list:
            assert call.kwargs["date"] == today

    @pytest.mark.asyncio
    async def test_all_categories_fail_still_returns_dict(self) -> None:
        """All categories failing still returns a structured dict (no raise)."""
        jobs = _make_analytics_jobs()
        mock_service = MagicMock()
        mock_service.generate_briefing = AsyncMock(
            side_effect=RuntimeError("All LLM providers failed")
        )

        with patch.object(jobs, "_build_briefing_service", return_value=mock_service):
            result = await jobs.generate_daily_briefing()

        assert result["categories_generated"] == 0
        assert result["categories_total"] == 4
        # Every category has an error entry.
        for cat in ("general", "finance", "tech", "ai"):
            assert "error" in result["results"][cat]

    @pytest.mark.asyncio
    async def test_result_includes_per_category_summary(self) -> None:
        """Result dict includes per-category summary (briefing_id, summary_present, items_count)."""
        jobs = _make_analytics_jobs()
        mock_service = MagicMock()
        mock_service.generate_briefing = AsyncMock(
            return_value=_make_mock_briefing_result(category="tech", briefing_id=99)
        )

        with patch.object(jobs, "_build_briefing_service", return_value=mock_service):
            result = await jobs.generate_daily_briefing()

        tech_result = result["results"]["tech"]
        assert tech_result["briefing_id"] == 99
        assert tech_result["summary_present"] is True
        assert tech_result["items_count"] == 1


class TestBriefingSchedulerCronRegistration:
    """Tests for cron registration in lifecycle._setup_scheduler (R-briefing-006).

    Uses source inspection because _setup_scheduler requires a full container.
    The test verifies the daily_briefing_generation job block uses:
    - CronTrigger(hour=8, minute=0, timezone=ZoneInfo("Asia/Shanghai"))
    - Job name mentions "4 categories"
    - max_instances=1, coalesce=True

    Spec R-briefing-006: cron `0 8 * * *` Asia/Shanghai.

    Block extraction uses ``split("scheduler.add_job(")`` rather than regex
    because CronTrigger args contain nested parens (ZoneInfo("...")) which
    break simple ``CronTrigger\\(([^)]+)\\)`` patterns. Splitting isolates
    the exact add_job chunk for daily_briefing_generation.
    """

    @staticmethod
    def _read_lifecycle_source() -> str:
        """Read lifecycle.py source for static analysis."""
        from src.container import lifecycle

        return inspect.getsource(lifecycle)

    @classmethod
    def _find_briefing_job_block(cls) -> str:
        """Extract the scheduler.add_job block containing daily_briefing_generation.

        Splits source at each ``scheduler.add_job(`` boundary and returns the
        chunk containing ``id="daily_briefing_generation"``. This avoids regex
        issues with nested parens in CronTrigger(ZoneInfo("...)")).
        """
        source = cls._read_lifecycle_source()
        chunks = source.split("scheduler.add_job(")
        for chunk in chunks:
            if 'id="daily_briefing_generation"' in chunk:
                return chunk
        return ""

    def test_briefing_job_block_exists(self) -> None:
        """daily_briefing_generation job block is registered in lifecycle."""
        block = self._find_briefing_job_block()
        assert block, "daily_briefing_generation job not found in lifecycle._setup_scheduler"

    def test_cron_trigger_uses_hour_8(self) -> None:
        """CronTrigger for daily_briefing_generation uses hour=8 (not hour=7)."""
        block = self._find_briefing_job_block()
        assert block, "daily_briefing_generation job block not found"
        assert (
            "hour=8" in block
        ), f"CronTrigger must use hour=8 per spec R-briefing-006. Block: {block[:200]}"
        assert (
            "hour=7" not in block
        ), "CronTrigger must NOT use hour=7 (old value, spec requires hour=8)"

    def test_cron_trigger_uses_minute_0(self) -> None:
        """CronTrigger for daily_briefing_generation uses minute=0."""
        block = self._find_briefing_job_block()
        assert block, "daily_briefing_generation job block not found"
        assert "minute=0" in block

    def test_cron_trigger_uses_asia_shanghai_timezone(self) -> None:
        """CronTrigger uses Asia/Shanghai timezone per spec R-briefing-006."""
        block = self._find_briefing_job_block()
        assert block, "daily_briefing_generation job block not found"
        assert (
            "Asia/Shanghai" in block
        ), f"CronTrigger must use Asia/Shanghai timezone. Block: {block[:200]}"

    def test_job_name_mentions_4_categories(self) -> None:
        """Job name mentions '4 categories' to reflect the 4-briefing generation."""
        block = self._find_briefing_job_block()
        assert block, "daily_briefing_generation job block not found"
        match = re.search(r'name="([^"]+)"', block)
        assert match is not None, f"Job name not found in block: {block[:200]}"
        job_name = match.group(1)
        assert (
            "4 categories" in job_name.lower()
        ), f"Job name should mention '4 categories', got: {job_name}"

    def test_job_uses_max_instances_1_and_coalesce(self) -> None:
        """Job uses max_instances=1 + coalesce=True per spec R-briefing-006."""
        block = self._find_briefing_job_block()
        assert block, "daily_briefing_generation job block not found"
        assert "max_instances=1" in block
        assert "coalesce=True" in block


class TestBriefingServiceBuilder:
    """Tests for AnalyticsJobs._build_briefing_service helper (T010)."""

    def test_build_briefing_service_returns_none_when_container_unavailable(self) -> None:
        """_build_briefing_service returns None (not raise) when container/LLM unavailable."""
        jobs = _make_analytics_jobs()

        with patch(
            "container.get_container",
            side_effect=RuntimeError("Container not initialized"),
        ):
            service = jobs._build_briefing_service()

        assert service is None

    def test_build_briefing_service_returns_none_when_llm_none(self) -> None:
        """_build_briefing_service returns None when llm_client is None."""
        jobs = _make_analytics_jobs()
        mock_container = MagicMock()
        mock_container.llm_client.return_value = None

        with patch("container.get_container", return_value=mock_container):
            service = jobs._build_briefing_service()

        assert service is None
