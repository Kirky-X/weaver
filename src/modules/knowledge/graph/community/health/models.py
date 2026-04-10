# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Community health data models for diagnosing and tracking issues.

Defines the data structures for community health diagnostics including
health status, issue types, and diagnostic reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class CommunityHealthStatus(StrEnum):
    """Health status of community system.

    HEALTHY: All communities are properly configured with reports.
    MODERATE: Minor issues like stale reports or minor count mismatches.
    DEGRADED: Significant issues like empty communities or hierarchy breaks.
    CRITICAL: Severe issues like many empty communities or no valid communities.
    """

    HEALTHY = "healthy"
    MODERATE = "moderate"
    DEGRADED = "degraded"
    CRITICAL = "critical"


class IssueType(StrEnum):
    """Types of community health issues."""

    EMPTY_COMMUNITY = "empty_community"
    ENTITY_COUNT_MISMATCH = "entity_count_mismatch"
    MISSING_REPORT = "missing_report"
    STALE_REPORT = "stale_report"
    HIERARCHY_BREAK = "hierarchy_break"
    LOW_MODULARITY = "low_modularity"


@dataclass
class HealthIssue:
    """A single community health issue.

    Attributes:
        issue_type: Type of the issue.
        severity: Severity level ("low", "medium", "high").
        community_id: ID of the affected community, if applicable.
        description: Human-readable description of the issue.
        suggestion: Suggested fix for the issue.
        auto_repairable: Whether this issue can be automatically fixed.
    """

    issue_type: IssueType
    severity: str  # "low", "medium", "high"
    description: str
    suggestion: str
    community_id: str | None = None
    auto_repairable: bool = False


@dataclass
class CommunityHealthReport:
    """Complete community health diagnostic report.

    Attributes:
        status: Overall health status.
        score: Health score (0-100, higher is better).
        issues: List of detected issues.
        metrics: Key metrics about communities.
        checked_at: Timestamp of the diagnostic.
    """

    status: CommunityHealthStatus
    score: float  # 0-100
    issues: list[HealthIssue] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "status": self.status.value,
            "score": self.score,
            "issues": [
                {
                    "issue_type": issue.issue_type.value,
                    "severity": issue.severity,
                    "community_id": issue.community_id,
                    "description": issue.description,
                    "suggestion": issue.suggestion,
                    "auto_repairable": issue.auto_repairable,
                }
                for issue in self.issues
            ],
            "metrics": self.metrics,
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass
class RepairResult:
    """Result of a repair operation.

    Attributes:
        repair_type: Type of repair performed.
        affected_count: Number of communities affected.
        success: Whether the repair was successful.
        error: Error message if repair failed.
    """

    repair_type: str
    affected_count: int = 0
    success: bool = True
    error: str | None = None


@dataclass
class RepairSummary:
    """Summary of multiple repair operations.

    Attributes:
        results: List of individual repair results.
        total_repaired: Total number of items repaired.
        duration_ms: Total duration in milliseconds.
    """

    results: list[RepairResult] = field(default_factory=list)
    total_repaired: int = 0
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "results": [
                {
                    "repair_type": r.repair_type,
                    "affected_count": r.affected_count,
                    "success": r.success,
                    "error": r.error,
                }
                for r in self.results
            ],
            "total_repaired": self.total_repaired,
            "duration_ms": self.duration_ms,
        }
