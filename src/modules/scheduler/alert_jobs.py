# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Alert jobs for scheduler: trend alert evaluation (T019 / R-alert-002).

Responsibilities:
- Evaluate trend alert rules hourly via TrendAlertEvaluator (T018)
- Graceful degradation when trend_detector or sentiment_analyzer is None
- Single-responsibility sub-class of the SchedulerJobs composition root

The job runs hourly (CRON minute=0) and delegates to TrendAlertEvaluator
which queries enabled alert_rules, evaluates trend_spike/trend_drop/
sentiment_shift rules, and inserts alert_events with 24h dedup.

Constructor injection (Rule — Protocol types, not concrete classes):
    ``__init__(relational_pool, trend_detector, sentiment_analyzer)``
    accepts any pool implementing RelationalPool and any services
    implementing TrendDetectionProtocol / SentimentTrendProtocol. Both
    trend services are optional (None) — when either is None, the job
    logs a warning and returns 0 (graceful skip, not an error). This
    allows the scheduler to start even when graph DB (for TrendDetector)
    or relational pool (for SentimentTrendAnalyzer) is unavailable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.observability import get_logger
from modules.alert import TrendAlertEvaluator
from modules.scheduler.wrapper import scheduled_task

if TYPE_CHECKING:
    from core.protocols import RelationalPool
    from core.protocols.services import SentimentTrendProtocol, TrendDetectionProtocol

log = get_logger(__name__)


class AlertJobs:
    """Scheduler jobs for trend alerting (T019 / R-alert-002).

    Handles hourly evaluation of trend alert rules. Delegates to
    TrendAlertEvaluator (T018) which performs the actual rule evaluation,
    dedup, and alert_events insertion.

    Implements: hourly trend alert evaluation (CRON minute=0).
    """

    def __init__(
        self,
        relational_pool: RelationalPool,
        trend_detector: TrendDetectionProtocol | None = None,
        sentiment_analyzer: SentimentTrendProtocol | None = None,
    ) -> None:
        self._relational_pool = relational_pool
        self._trend_detector = trend_detector
        self._sentiment_analyzer = sentiment_analyzer

    @scheduled_task("evaluate_trend_alerts", timeout_seconds=300)
    async def evaluate_trend_alerts(self) -> int:
        """Evaluate trend alert rules and insert alert_events (T019 / R-alert-002).

        Constructs a TrendAlertEvaluator with the injected pool, trend_detector,
        and sentiment_analyzer, then calls ``evaluate()`` which queries
        enabled alert_rules, evaluates each rule, and inserts alert_events
        for triggers passing 24h dedup.

        Graceful skip (R-alert-002 Constraints):
            When trend_detector or sentiment_analyzer is None, the job logs
            a warning and returns 0. This is NOT an error — the scheduler
            must not be blocked by missing optional dependencies. The trend
            services may be unavailable when the graph DB (TrendDetector)
            or relational pool (SentimentTrendAnalyzer) is not configured.

        Returns:
            Number of new alert_events inserted. Returns 0 when trend
            services are unavailable (graceful skip) or when no rules
            triggered. On exception, the @scheduled_task wrapper returns -2
            (scheduler convention — see wrapper.py).

        Raises:
            Nothing — exceptions are caught by the @scheduled_task wrapper
            and returned as -2. This ensures the scheduler is never blocked
            by evaluator errors (R-alert-002: failure doesn't block next
            execution).
        """
        if self._trend_detector is None or self._sentiment_analyzer is None:
            log.warning(
                "evaluate_trend_alerts_skipped",
                reason="missing_dependencies",
                trend_detector=self._trend_detector is not None,
                sentiment_analyzer=self._sentiment_analyzer is not None,
            )
            return 0

        evaluator = TrendAlertEvaluator(
            pool=self._relational_pool,
            trend_detector=self._trend_detector,
            sentiment_analyzer=self._sentiment_analyzer,
        )
        return await evaluator.evaluate()


__all__ = ["AlertJobs"]
