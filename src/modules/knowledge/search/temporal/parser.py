# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Temporal inference engine - Chinese relative time expression parsing."""

import re
from datetime import datetime, timedelta

from core.observability.logging import get_logger

from .schemas import TimeAnchor, TimeWindow

log = get_logger("search.temporal.parser")

# Chinese relative time patterns
PATTERNS: dict[str, object] = {
    # 今天
    r"(?:今天|today)\b": lambda ref: ref.date(),
    # 昨天
    r"(?:昨天|yesterday)\b": lambda ref: ref - timedelta(days=1),
    # N天前
    r"(\d+)\s*(?:个?\s*)?(?:天|days?)\s*前\b": lambda ref, m: ref - timedelta(days=int(m.group(1))),
    # 本周
    r"(?:本周|this week)\b": lambda ref: ref - timedelta(days=ref.weekday()),
    # 上周
    r"(?:上周|last week)\b": lambda ref: ref - timedelta(weeks=1),
    # 下周
    r"(?:下周|next week)\b": lambda ref: ref + timedelta(weeks=1),
    # 本月
    r"(?:本月|this month)\b": lambda ref: ref.replace(day=1),
    # 上月
    r"(?:上月|last month)\b": lambda ref: ref.replace(day=1) - timedelta(days=1),
    # 下月
    r"(?:下月|next month)\b": lambda ref: ref.replace(day=1) + timedelta(days=31),
    # 上/下周 + 星期几 (e.g. 上周五, 下周一)
    r"[上下]周[一二三四五六日天]": None,
    # English last/next + weekday
    # English last/next + weekday
    r"(?:last|next)\s*(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b": None,
    # N个月前
    r"(\d+)\s*(?:个?\s*)?(?:月|months?)\s*前\b": lambda ref, m: (
        ref - timedelta(days=30 * int(m.group(1)))
    ),
}

DAY_MAP: dict[str, int] = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 0,
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class TemporalParser:
    """Temporal inference engine - Chinese relative time expression parsing."""

    def parse(self, query: str, reference: datetime | None = None) -> list[TimeAnchor]:
        """Parse temporal expressions from query.

        Args:
            query: The user's search query.
            reference: Reference datetime for relative resolution. Defaults to UTC now.

        Returns:
            List of TimeAnchor with detected temporal expressions.
        """
        reference = reference or datetime.utcnow()
        anchors: list[TimeAnchor] = []

        for pattern, resolver in PATTERNS.items():
            for match in re.finditer(pattern, query, re.IGNORECASE):
                if resolver is None:
                    resolved = self._resolve_day_expression(match.group(0), reference)
                elif callable(resolver):
                    try:
                        resolved = resolver(reference, match)
                    except TypeError:
                        resolved = resolver(reference)
                else:
                    continue

                anchors.append(
                    TimeAnchor(
                        reference_time=reference,
                        expression=match.group(0),
                        resolved=resolved,
                    )
                )

        return anchors

    def _resolve_day_expression(self, expr: str, reference: datetime) -> datetime:
        """Resolve 'last Monday' / 'next Friday' / '上周五' style expressions."""
        # Chinese: 上/下周X (e.g. 上周五, 下周一)
        match = re.search(r"([上下])周([一二三四五六日天])", expr, re.IGNORECASE)
        if match:
            direction_char, day_char = match.groups()
            day = DAY_MAP.get(day_char)
            if day is None:
                return reference
            direction = "last" if direction_char == "上" else "next"
            return self._calc_weekday(direction, day, reference)

        # English: last/next + weekday
        match = re.search(
            r"(last|next)\s*([一二三四五六日周]+|monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
            expr,
            re.IGNORECASE,
        )
        if not match:
            return reference

        direction, day_str = match.groups()
        day = DAY_MAP.get(day_str.lower())

        if day is None:
            log.warning("invalid_day_expression", expression=expr)
            return reference

        return self._calc_weekday(direction.lower(), day, reference)

    def _calc_weekday(self, direction: str, target_weekday: int, reference: datetime) -> datetime:
        """Calculate target date for a given weekday direction."""
        current_weekday = reference.weekday()

        if direction == "last":
            delta = (current_weekday - target_weekday) % 7
            if delta == 0:
                delta = 7
            return reference - timedelta(days=delta)
        else:
            delta = (target_weekday - current_weekday) % 7
            if delta == 0:
                delta = 7
            return reference + timedelta(days=delta)

    def resolve_time_window(self, anchors: list[TimeAnchor]) -> TimeWindow:
        """Parse temporal signals into a time window for filtering.

        Args:
            anchors: List of detected temporal signals.

        Returns:
            TimeWindow with start and end bounds.
        """
        if not anchors:
            return TimeWindow(start=None, end=None, relative_to_query=False)

        # Collect resolved timestamps
        resolved_times: list[datetime] = []
        for anchor in anchors:
            if anchor.resolved is not None:
                # Handle date objects (from "今天" pattern)
                val = anchor.resolved
                if hasattr(val, "hour"):
                    resolved_times.append(val)
                else:
                    # date object — convert to datetime
                    resolved_times.append(datetime(val.year, val.month, val.day))

        if not resolved_times:
            return TimeWindow(start=None, end=None, relative_to_query=False)

        earliest = min(resolved_times)
        latest = max(resolved_times)

        # Check if any relative expressions need window extension
        has_relative = any(
            anchor.expression.startswith(("last", "next", "上", "下"))
            or "ago" in anchor.expression.lower()
            for anchor in anchors
        )

        if has_relative:
            time_range = timedelta(days=7)
            return TimeWindow(
                start=earliest - time_range,
                end=latest,
                relative_to_query=True,
            )

        return TimeWindow(
            start=earliest,
            end=latest,
            relative_to_query=False,
        )

    def extract_patterns_from_text(self, text: str) -> list[str]:
        """Extract common temporal keywords for intent classifier hint."""
        keywords: list[str] = []
        for pattern in PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                keywords.append(pattern)
        return list(set(keywords))
