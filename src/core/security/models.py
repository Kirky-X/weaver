# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Data models for URL security checking."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class URLRisk(Enum):
    """URL risk level classification.

    Risk levels are ordered from lowest to highest:
    SAFE < LOW < MEDIUM < HIGH < BLOCKED
    """

    SAFE = "safe"
    """URL is considered safe."""

    LOW = "low"
    """Low risk - suspicious but not confirmed malicious."""

    MEDIUM = "medium"
    """Medium risk - multiple suspicious indicators."""

    HIGH = "high"
    """High risk - likely malicious."""

    BLOCKED = "blocked"
    """Confirmed malicious - should be blocked."""

    def __gt__(self, other: "URLRisk") -> bool:
        """Compare risk levels."""
        order = [URLRisk.SAFE, URLRisk.LOW, URLRisk.MEDIUM, URLRisk.HIGH, URLRisk.BLOCKED]
        return order.index(self) > order.index(other)

    def __lt__(self, other: "URLRisk") -> bool:
        """Compare risk levels."""
        order = [URLRisk.SAFE, URLRisk.LOW, URLRisk.MEDIUM, URLRisk.HIGH, URLRisk.BLOCKED]
        return order.index(self) < order.index(other)


class CheckSource(Enum):
    """Source of a security check result."""

    CACHE = "cache"
    """Result from cache."""

    SSRF = "ssrf"
    """SSRF protection check."""

    URLHAUS_API = "urlhaus_api"
    """URLhaus API check."""

    PHISHTANK = "phishtank"
    """PhishTank blacklist check."""

    HEURISTIC = "heuristic"
    """Heuristic analysis check."""

    SSL = "ssl"
    """SSL certificate verification."""


@dataclass
class CheckResult:
    """Result from a single security checker.

    Each checker produces a CheckResult with its assessment of the URL.
    """

    source: CheckSource
    """Which checker produced this result."""

    risk: URLRisk
    """Risk level assigned by this checker."""

    message: str = ""
    """Human-readable description of the result."""

    details: dict[str, Any] = field(default_factory=dict)
    """Additional details about the check result."""

    @property
    def should_fallback(self) -> bool:
        """Check if this result indicates fallback to local checks is needed."""
        return self.details.get("should_fallback", False)


@dataclass
class ValidationResult:
    """Aggregated result from all security checks.

    Combines results from all checkers into a final verdict.
    """

    url: str
    """The URL that was validated."""

    risk: URLRisk
    """Final risk level (highest among all checks)."""

    is_safe: bool
    """Whether the URL is considered safe (SAFE or LOW risk)."""

    checks: list[CheckResult] = field(default_factory=list)
    """Individual check results."""

    cached: bool = False
    """Whether this result came from cache."""

    @property
    def primary_reason(self) -> str | None:
        """Get the primary reason for the risk assessment.

        Returns the first HIGH or BLOCKED check message.
        """
        for check in self.checks:
            if check.risk in (URLRisk.HIGH, URLRisk.BLOCKED):
                return f"[{check.source.value}] {check.message}"
        return None

    def get_check_by_source(self, source: CheckSource) -> CheckResult | None:
        """Get a specific check result by source.

        Args:
            source: The check source to look for.

        Returns:
            The CheckResult if found, None otherwise.
        """
        for check in self.checks:
            if check.source == source:
                return check
        return None
