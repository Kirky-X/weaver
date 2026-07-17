# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for AlertJobs scheduler integration (T019 / R-alert-002).

Covers:
- AlertJobs.evaluate_trend_alerts delegates to TrendAlertEvaluator.evaluate
- Graceful skip (returns 0) when trend_detector or sentiment_analyzer is None
- Error propagation: evaluator exceptions return -2 (scheduled_task convention)
- Cron registration in lifecycle._setup_scheduler: hourly (minute=0),
  max_instances=1, coalesce=True, job id="evaluate_trend_alerts"
- SchedulerJobs facade delegates evaluate_trend_alerts to AlertJobs

The cron registration test uses source inspection (``inspect.getsource``)
because ``_setup_scheduler`` requires a full container to invoke. Source
inspection directly verifies spec R-alert-002 (hourly cron) and acts as a
regression guard — same pattern as test_briefing_scheduler.py.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_alert_jobs(
    *,
    trend_detector: object | None = MagicMock(),
    sentiment_analyzer: object | None = MagicMock(),
) -> AlertJobs:
    """Build an AlertJobs instance with mocked dependencies.

    Defaults to non-None detector/analyzer so evaluate_trend_alerts proceeds
    to the evaluator path. Pass None for either to test graceful skip.
    """
    from modules.scheduler.alert_jobs import AlertJobs

    return AlertJobs(
        relational_pool=MagicMock(),
        trend_detector=trend_detector,
        sentiment_analyzer=sentiment_analyzer,
    )


class TestEvaluateTrendAlertsJob:
    """Tests for AlertJobs.evaluate_trend_alerts (T019)."""

    @pytest.mark.asyncio
    async def test_delegates_to_evaluator_evaluate(self) -> None:
        """evaluate_trend_alerts constructs TrendAlertEvaluator and calls evaluate()."""
        jobs = _make_alert_jobs()

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate = AsyncMock(return_value=3)

        with patch(
            "modules.scheduler.alert_jobs.TrendAlertEvaluator",
            return_value=mock_evaluator,
        ) as mock_ctor:
            count = await jobs.evaluate_trend_alerts()

        assert count == 3
        mock_evaluator.evaluate.assert_awaited_once()
        # Verify constructor was called with the injected dependencies.
        assert mock_ctor.call_count == 1
        ctor_args, ctor_kwargs = mock_ctor.call_args
        # Constructor accepts pool, trend_detector, sentiment_analyzer as kwargs.
        assert ctor_kwargs.get("trend_detector") is jobs._trend_detector
        assert ctor_kwargs.get("sentiment_analyzer") is jobs._sentiment_analyzer

    @pytest.mark.asyncio
    async def test_skips_when_trend_detector_none(self) -> None:
        """When trend_detector is None, job returns 0 (graceful skip, not error)."""
        jobs = _make_alert_jobs(trend_detector=None)

        with patch("modules.scheduler.alert_jobs.TrendAlertEvaluator") as mock_ctor:
            count = await jobs.evaluate_trend_alerts()

        assert count == 0
        mock_ctor.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_sentiment_analyzer_none(self) -> None:
        """When sentiment_analyzer is None, job returns 0 (graceful skip)."""
        jobs = _make_alert_jobs(sentiment_analyzer=None)

        with patch("modules.scheduler.alert_jobs.TrendAlertEvaluator") as mock_ctor:
            count = await jobs.evaluate_trend_alerts()

        assert count == 0
        mock_ctor.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_both_none(self) -> None:
        """When both detector and analyzer are None, job returns 0."""
        jobs = _make_alert_jobs(trend_detector=None, sentiment_analyzer=None)

        with patch("modules.scheduler.alert_jobs.TrendAlertEvaluator") as mock_ctor:
            count = await jobs.evaluate_trend_alerts()

        assert count == 0
        mock_ctor.assert_not_called()

    @pytest.mark.asyncio
    async def test_evaluator_exception_returns_negative_two(self) -> None:
        """Evaluator exception is caught by @scheduled_task wrapper → returns -2.

        The @scheduled_task decorator catches all exceptions and returns -2
        (scheduler convention). This test verifies the wrapper is applied
        and that evaluator errors do NOT propagate as exceptions (which
        would crash the scheduler).
        """
        jobs = _make_alert_jobs()

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        with patch(
            "modules.scheduler.alert_jobs.TrendAlertEvaluator",
            return_value=mock_evaluator,
        ):
            result = await jobs.evaluate_trend_alerts()

        # @scheduled_task returns -2 on exception (wrapper.py line 109).
        assert result == -2

    @pytest.mark.asyncio
    async def test_returns_zero_when_evaluator_inserts_nothing(self) -> None:
        """When evaluator returns 0 (no triggers), job returns 0."""
        jobs = _make_alert_jobs()

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate = AsyncMock(return_value=0)

        with patch(
            "modules.scheduler.alert_jobs.TrendAlertEvaluator",
            return_value=mock_evaluator,
        ):
            count = await jobs.evaluate_trend_alerts()

        assert count == 0

    @pytest.mark.asyncio
    async def test_uses_injected_relational_pool(self) -> None:
        """evaluate_trend_alerts passes the injected relational_pool to the evaluator."""
        mock_pool = MagicMock()
        from modules.scheduler.alert_jobs import AlertJobs

        jobs = AlertJobs(
            relational_pool=mock_pool,
            trend_detector=MagicMock(),
            sentiment_analyzer=MagicMock(),
        )

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate = AsyncMock(return_value=0)

        with patch(
            "modules.scheduler.alert_jobs.TrendAlertEvaluator",
            return_value=mock_evaluator,
        ) as mock_ctor:
            await jobs.evaluate_trend_alerts()

        ctor_args, ctor_kwargs = mock_ctor.call_args
        assert ctor_kwargs.get("pool") is mock_pool


class TestAlertJobsCronRegistration:
    """Tests for cron registration in lifecycle._setup_scheduler (R-alert-002).

    Uses source inspection because _setup_scheduler requires a full container.
    The test verifies the evaluate_trend_alerts job block uses:
    - CronTrigger with minute=0 (hourly — runs at top of every hour)
    - Job id="evaluate_trend_alerts"
    - max_instances=1, coalesce=True

    Spec R-alert-002: hourly execution (CRON `0 * * * *`).

    Block extraction uses ``split("scheduler.add_job(")`` rather than regex
    because CronTrigger args may contain nested parens. Same pattern as
    test_briefing_scheduler.py::TestBriefingSchedulerCronRegistration.
    """

    @staticmethod
    def _read_lifecycle_source() -> str:
        """Read lifecycle.py source for static analysis."""
        from src.container import lifecycle

        return inspect.getsource(lifecycle)

    @classmethod
    def _find_alert_job_block(cls) -> str:
        """Extract the scheduler.add_job block containing evaluate_trend_alerts.

        Splits source at each ``scheduler.add_job(`` boundary and returns the
        chunk containing ``id="evaluate_trend_alerts"``.
        """
        source = cls._read_lifecycle_source()
        chunks = source.split("scheduler.add_job(")
        for chunk in chunks:
            if 'id="evaluate_trend_alerts"' in chunk:
                return chunk
        return ""

    def test_alert_job_block_exists(self) -> None:
        """evaluate_trend_alerts job block is registered in lifecycle."""
        block = self._find_alert_job_block()
        assert block, "evaluate_trend_alerts job not found in lifecycle._setup_scheduler"

    def test_cron_trigger_uses_minute_0(self) -> None:
        """CronTrigger for evaluate_trend_alerts uses minute=0 (top of every hour)."""
        block = self._find_alert_job_block()
        assert block, "evaluate_trend_alerts job block not found"
        assert (
            "minute=0" in block
        ), f"CronTrigger must use minute=0 for hourly execution. Block: {block[:200]}"

    def test_job_id_is_evaluate_trend_alerts(self) -> None:
        """Job id is exactly 'evaluate_trend_alerts'."""
        block = self._find_alert_job_block()
        assert block, "evaluate_trend_alerts job block not found"
        assert 'id="evaluate_trend_alerts"' in block

    def test_job_uses_max_instances_1(self) -> None:
        """Job uses max_instances=1 per spec R-alert-002."""
        block = self._find_alert_job_block()
        assert block, "evaluate_trend_alerts job block not found"
        assert "max_instances=1" in block

    def test_job_uses_coalesce_true(self) -> None:
        """Job uses coalesce=True per spec R-alert-002."""
        block = self._find_alert_job_block()
        assert block, "evaluate_trend_alerts job block not found"
        assert "coalesce=True" in block

    def test_job_calls_evaluate_trend_alerts_method(self) -> None:
        """Job target is jobs.evaluate_trend_alerts (the SchedulerJobs facade method)."""
        block = self._find_alert_job_block()
        assert block, "evaluate_trend_alerts job block not found"
        assert "jobs.evaluate_trend_alerts" in block


class TestSchedulerJobsDelegation:
    """Tests for SchedulerJobs facade delegation to AlertJobs (T019).

    SchedulerJobs is a composition root — evaluate_trend_alerts on the facade
    delegates to the internal AlertJobs instance. This mirrors the existing
    delegation pattern for ConsistencyJobs/MaintenanceJobs/AnalyticsJobs.
    """

    def test_scheduler_jobs_has_evaluate_trend_alerts_method(self) -> None:
        """SchedulerJobs exposes evaluate_trend_alerts as a delegation method."""
        from modules.scheduler.jobs import SchedulerJobs

        assert hasattr(
            SchedulerJobs, "evaluate_trend_alerts"
        ), "SchedulerJobs must expose evaluate_trend_alerts to delegate to AlertJobs"

    @pytest.mark.asyncio
    async def test_delegates_to_alert_jobs(self) -> None:
        """SchedulerJobs.evaluate_trend_alerts delegates to internal AlertJobs."""
        # Build SchedulerJobs with minimal mocked deps.
        # We patch AlertJobs to avoid needing real trend_detector/sentiment_analyzer.
        with patch("modules.scheduler.jobs.AlertJobs") as mock_alert_jobs_cls:
            mock_alert_jobs = MagicMock()
            mock_alert_jobs.evaluate_trend_alerts = AsyncMock(return_value=5)
            mock_alert_jobs_cls.return_value = mock_alert_jobs

            from modules.scheduler.jobs import SchedulerJobs

            jobs = SchedulerJobs(
                relational_pool=MagicMock(),
                cache=MagicMock(),
                graph_writer=MagicMock(),
                vector_repo=MagicMock(),
                article_repo=MagicMock(),
                source_authority_repo=MagicMock(),
                pending_sync_repo=MagicMock(),
                trend_detector=MagicMock(),
                sentiment_analyzer=MagicMock(),
            )

            count = await jobs.evaluate_trend_alerts()

        assert count == 5
        mock_alert_jobs.evaluate_trend_alerts.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_constructor_passes_trend_detector_to_alert_jobs(self) -> None:
        """SchedulerJobs passes trend_detector to AlertJobs constructor."""
        mock_detector = MagicMock()
        mock_analyzer = MagicMock()

        with patch("modules.scheduler.jobs.AlertJobs") as mock_alert_jobs_cls:
            mock_alert_jobs = MagicMock()
            mock_alert_jobs_cls.return_value = mock_alert_jobs

            from modules.scheduler.jobs import SchedulerJobs

            SchedulerJobs(
                relational_pool=MagicMock(),
                cache=MagicMock(),
                graph_writer=MagicMock(),
                vector_repo=MagicMock(),
                article_repo=MagicMock(),
                source_authority_repo=MagicMock(),
                pending_sync_repo=MagicMock(),
                trend_detector=mock_detector,
                sentiment_analyzer=mock_analyzer,
            )

        ctor_args, ctor_kwargs = mock_alert_jobs_cls.call_args
        assert ctor_kwargs.get("trend_detector") is mock_detector
        assert ctor_kwargs.get("sentiment_analyzer") is mock_analyzer

    @pytest.mark.asyncio
    async def test_constructor_defaults_trend_detector_none(self) -> None:
        """When trend_detector/sentiment_analyzer not provided, default to None.

        This allows SchedulerJobs to be constructed without trend services
        (backward compatibility — existing tests/callers don't pass them).
        AlertJobs handles None gracefully (returns 0).
        """
        with patch("modules.scheduler.jobs.AlertJobs") as mock_alert_jobs_cls:
            mock_alert_jobs = MagicMock()
            mock_alert_jobs_cls.return_value = mock_alert_jobs

            from modules.scheduler.jobs import SchedulerJobs

            SchedulerJobs(
                relational_pool=MagicMock(),
                cache=MagicMock(),
                graph_writer=MagicMock(),
                vector_repo=MagicMock(),
                article_repo=MagicMock(),
                source_authority_repo=MagicMock(),
                pending_sync_repo=MagicMock(),
            )

        ctor_args, ctor_kwargs = mock_alert_jobs_cls.call_args
        assert ctor_kwargs.get("trend_detector") is None
        assert ctor_kwargs.get("sentiment_analyzer") is None


class TestSchedulerModuleExports:
    """Tests for scheduler module __init__.py exports (T019)."""

    def test_alert_jobs_exported_from_scheduler_module(self) -> None:
        """AlertJobs is exported from the scheduler package __init__.py."""
        import modules.scheduler as scheduler_pkg

        assert hasattr(
            scheduler_pkg, "AlertJobs"
        ), "AlertJobs must be exported from modules.scheduler for container/lifecycle use"

    def test_alert_jobs_in_all(self) -> None:
        """AlertJobs is listed in modules.scheduler.__all__."""
        import modules.scheduler as scheduler_pkg

        assert "AlertJobs" in scheduler_pkg.__all__
