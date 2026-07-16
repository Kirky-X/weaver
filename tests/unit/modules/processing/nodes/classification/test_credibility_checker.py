# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for RuleBasedCredibilityCheckerNode._calc_timeliness.

Regression tests for Bug-A: TypeError when publish_time is str (not datetime).

Root cause: cleaner.py backfills publish_time as str(date), but _calc_timeliness
expected datetime. Fix: defensive _to_datetime helper handles str/datetime/None.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from modules.processing.nodes.classification.credibility_checker import (
    RuleBasedCredibilityCheckerNode,
)


class TestCalcTimeliness:
    """Tests for _calc_timeliness defensive type handling."""

    @pytest.mark.parametrize(
        "publish_time,event_time,expected_min,expected_max,desc",
        [
            # Both None → default 0.7
            (None, None, 0.7, 0.7, "both_none"),
            # publish_time None → 0.7
            (None, "2026-01-01T00:00:00+00:00", 0.7, 0.7, "publish_none"),
            # event_time None → 0.7
            (datetime(2026, 1, 1, tzinfo=UTC), None, 0.7, 0.7, "event_none"),
            # Both datetime, within 6h → 1.00
            (
                datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
                1.00,
                1.00,
                "datetime_within_6h",
            ),
            # Both datetime, within 24h → 0.85
            (
                datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
                0.85,
                0.85,
                "datetime_within_24h",
            ),
            # Bug-A regression: publish_time as str (from cleaner.py backfill)
            # Before fix: TypeError: unsupported operand type(s) for -: 'str' and 'datetime.datetime'
            # After fix: should return 1.00 (within 6h)
            (
                "2026-01-01T12:00:00+00:00",
                "2026-01-01T10:00:00+00:00",
                1.00,
                1.00,
                "bug_a_str_publish_time",
            ),
            # publish_time as str (ISO without tz) + event_time as str
            (
                "2026-01-01T12:00:00",
                "2026-01-01T10:00:00",
                1.00,
                1.00,
                "str_no_tzinfo",
            ),
            # Mixed: publish_time str + event_time datetime
            (
                "2026-01-01T12:00:00+00:00",
                datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
                1.00,
                1.00,
                "mixed_str_datetime",
            ),
            # Both datetime, within 72h → 0.65
            (
                datetime(2026, 1, 3, 12, 0, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
                0.65,
                0.65,
                "datetime_within_72h",
            ),
            # Both datetime, within 168h (1 week) → 0.45
            (
                datetime(2026, 1, 7, 12, 0, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
                0.45,
                0.45,
                "datetime_within_168h",
            ),
            # Both datetime, > 168h → 0.30
            (
                datetime(2026, 1, 20, 12, 0, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
                0.30,
                0.30,
                "datetime_over_168h",
            ),
            # Invalid event_time str → 0.7 (graceful fallback)
            (
                datetime(2026, 1, 1, tzinfo=UTC),
                "not-a-date",
                0.7,
                0.7,
                "invalid_event_time_str",
            ),
            # Invalid publish_time str → 0.7 (graceful fallback)
            (
                "not-a-date",
                "2026-01-01T10:00:00+00:00",
                0.7,
                0.7,
                "invalid_publish_time_str",
            ),
        ],
    )
    def test_calc_timeliness_handles_various_types(
        self,
        publish_time,
        event_time,
        expected_min,
        expected_max,
        desc,
    ):
        """Test _calc_timeliness handles str/datetime/None inputs defensively.

        Regression: Bug-A TypeError when publish_time is str.
        """
        score = RuleBasedCredibilityCheckerNode._calc_timeliness(publish_time, event_time)
        assert (
            expected_min <= score <= expected_max
        ), f"test case '{desc}' failed: expected [{expected_min}, {expected_max}], got {score}"
