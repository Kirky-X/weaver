# Copyright (c) 2026 KirkyX. All Rights Reserved
"""ForgettingScheduler: Schedules event archival based on access frequency and importance.

Implements a tiered data retention policy:
- hot: 0-1 year (actively accessible)
- warm: 1-3 years (accessible with slight latency)
- cold: 3-7 years (archived, minimal access)
- expired: 7+ years (eligible for deletion)

High-importance events (>= IMPORTANCE_PRESERVE_THRESHOLD) are preserved
from archival regardless of staleness.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from core.observability.logging import get_logger

log = get_logger(__name__)


class ForgettingScheduler:
    """Schedules event archival based on access frequency and importance.

    Implements a tiered retention policy with importance-based preservation.
    Events that haven't been accessed in STALE_THRESHOLD_DAYS are marked
    as stale and become candidates for archival, unless their importance
    score meets the preservation threshold.
    """

    STALE_THRESHOLD_DAYS = 90
    IMPORTANCE_PRESERVE_THRESHOLD = 0.8

    # Retention tier boundaries (in days)
    HOT_THRESHOLD_DAYS = 365  # 1 year
    WARM_THRESHOLD_DAYS = 3 * 365  # 3 years
    COLD_THRESHOLD_DAYS = 7 * 365  # 7 years

    def mark_stale_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Mark events as stale if not accessed in 90 days.

        Args:
            events: List of event dicts with last_accessed field.

        Returns:
            Updated list of event dicts with stale field set.
        """
        now = datetime.now(UTC)
        threshold = now - timedelta(days=self.STALE_THRESHOLD_DAYS)

        result = []
        for event in events:
            updated_event = dict(event)
            last_accessed_str = event.get("last_accessed")

            if last_accessed_str:
                try:
                    last_accessed = datetime.fromisoformat(last_accessed_str)
                    if last_accessed.tzinfo is None:
                        last_accessed = last_accessed.replace(tzinfo=UTC)
                    updated_event["stale"] = last_accessed <= threshold
                except (ValueError, TypeError):
                    updated_event["stale"] = False
            else:
                updated_event["stale"] = False

            result.append(updated_event)

        return result

    def archive_stale_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Archive stale events (excluding high-importance ones).

        Events are archived if they are stale AND their importance
        is below the IMPORTANCE_PRESERVE_THRESHOLD.

        Args:
            events: List of event dicts with stale and importance fields.

        Returns:
            Updated list of event dicts with archived field set.
        """
        result = []
        for event in events:
            updated_event = dict(event)

            is_stale = event.get("stale", False)
            importance = event.get("importance", 0.0)

            if is_stale and importance < self.IMPORTANCE_PRESERVE_THRESHOLD:
                updated_event["archived"] = True
                log.debug(
                    "event_archived",
                    event_id=event.get("id"),
                    importance=importance,
                )
            else:
                updated_event["archived"] = False

            result.append(updated_event)

        return result

    def apply_retention_policy(self, event: dict[str, Any]) -> str:
        """Apply data retention policy: hot(1yr) → warm → cold(7yr).

        Classifies an event into a retention tier based on its age.

        Args:
            event: Event dict with created_at field.

        Returns:
            Retention tier: 'hot', 'warm', 'cold', or 'expired'.
        """
        created_at_str = event.get("created_at")

        if not created_at_str:
            return "hot"

        try:
            created_at = datetime.fromisoformat(created_at_str)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            return "hot"

        now = datetime.now(UTC)
        age_days = (now - created_at).days

        if age_days < self.HOT_THRESHOLD_DAYS:
            return "hot"
        elif age_days < self.WARM_THRESHOLD_DAYS:
            return "warm"
        elif age_days < self.COLD_THRESHOLD_DAYS:
            return "cold"
        else:
            return "expired"
