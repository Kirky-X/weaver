# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Security audit utilities for application startup.

This module provides startup-time security checks to detect potential
vulnerabilities before the application accepts requests.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from core.observability.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger("security_audit")


class SecurityCheckSeverity(str, Enum):
    """Security check severity levels."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass
class SecurityCheckResult:
    """Result of a security check.

    Attributes:
        name: Check name.
        severity: Issue severity.
        message: Description of the issue.
        file_path: File where issue was found (if applicable).
        line_number: Line number (if applicable).
        recommendation: How to fix the issue.
    """

    name: str
    severity: SecurityCheckSeverity
    message: str
    file_path: str | None = None
    line_number: int | None = None
    recommendation: str | None = None


@dataclass
class SecurityAuditReport:
    """Security audit report containing all check results.

    Attributes:
        results: List of security check results.
        passed: Whether all checks passed (no CRITICAL or HIGH issues).
    """

    results: list[SecurityCheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Check if audit passed (no CRITICAL or HIGH issues)."""
        return not any(
            r.severity in (SecurityCheckSeverity.CRITICAL, SecurityCheckSeverity.HIGH)
            for r in self.results
        )

    @property
    def critical_count(self) -> int:
        """Count of CRITICAL issues."""
        return sum(1 for r in self.results if r.severity == SecurityCheckSeverity.CRITICAL)

    @property
    def high_count(self) -> int:
        """Count of HIGH issues."""
        return sum(1 for r in self.results if r.severity == SecurityCheckSeverity.HIGH)

    @property
    def medium_count(self) -> int:
        """Count of MEDIUM issues."""
        return sum(1 for r in self.results if r.severity == SecurityCheckSeverity.MEDIUM)


# ── Detection Patterns ─────────────────────────────────────────────────────

# f-string with SQL keywords (potential SQL injection)
_SQL_FSTRING_PATTERN = re.compile(
    r'f["\'].*\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|JOIN|MATCH|CREATE|MERGE)\b.*["\']',
    re.IGNORECASE,
)

# f-string with Cypher keywords (potential Cypher injection)
_CYPHER_FSTRING_PATTERN = re.compile(
    r'f["\'].*\b(MATCH|CREATE|MERGE|RETURN|WHERE|WITH|DELETE|SET|UNWIND)\b.*["\']',
    re.IGNORECASE,
)

# pickle.load usage
_PICKLE_LOAD_PATTERN = re.compile(r"pickle\.load[s]?\s*\(")

# Hardcoded secrets patterns
_SECRET_PATTERNS = [
    re.compile(r'password\s*=\s*["\'][^"\']+(["\'])', re.IGNORECASE),
    re.compile(r'api_key\s*=\s*["\'][^"\']+(["\'])', re.IGNORECASE),
    re.compile(r'secret\s*=\s*["\'][^"\']+(["\'])', re.IGNORECASE),
    re.compile(r'token\s*=\s*["\'][^"\']+(["\'])', re.IGNORECASE),
]


def check_env_security() -> list[SecurityCheckResult]:
    """Check environment variable security configuration.

    Returns:
        List of security issues found.
    """
    results = []

    # Check for required security env vars
    security_env_vars = {
        "INDEX_SIGNING_KEY": "BM25 index signing key",
        "SECRET_KEY": "Application secret key",
    }

    for env_var, description in security_env_vars.items():
        if not os.environ.get(env_var):
            results.append(
                SecurityCheckResult(
                    name=f"missing_{env_var.lower()}",
                    severity=SecurityCheckSeverity.MEDIUM,
                    message=f"Security environment variable {env_var} is not set",
                    recommendation=f"Set {env_var} environment variable for {description}",
                )
            )

    # Check for development mode indicators
    if os.environ.get("ENVIRONMENT", "development").lower() == "development":
        results.append(
            SecurityCheckResult(
                name="development_mode",
                severity=SecurityCheckSeverity.INFO,
                message="Application running in development mode",
                recommendation="Set ENVIRONMENT=production for production deployments",
            )
        )

    return results


def check_code_patterns(source_dir: str = "src") -> list[SecurityCheckResult]:
    """Scan source code for potential security issues.

    Args:
        source_dir: Directory to scan.

    Returns:
        List of security issues found.
    """
    results = []

    try:
        import pathlib

        for py_file in pathlib.Path(source_dir).rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                lines = content.splitlines()

                for line_num, line in enumerate(lines, start=1):
                    # Check for SQL f-string injection
                    if (
                        _SQL_FSTRING_PATTERN.search(line)
                        and "$" not in line
                        and ":param" not in line.lower()
                    ):
                        results.append(
                            SecurityCheckResult(
                                name="sql_injection_risk",
                                severity=SecurityCheckSeverity.HIGH,
                                message="Potential SQL injection: f-string used in SQL query",
                                file_path=str(py_file),
                                line_number=line_num,
                                recommendation="Use parameterized queries with $1, $2 placeholders",
                            )
                        )

                    # Check for Cypher f-string injection
                    if _CYPHER_FSTRING_PATTERN.search(line) and "$" not in line:
                        results.append(
                            SecurityCheckResult(
                                name="cypher_injection_risk",
                                severity=SecurityCheckSeverity.HIGH,
                                message="Potential Cypher injection: f-string used in Cypher query",
                                file_path=str(py_file),
                                line_number=line_num,
                                recommendation="Use parameterized Cypher with $param placeholders",
                            )
                        )

                    # Check for pickle.load
                    if (
                        _PICKLE_LOAD_PATTERN.search(line)
                        and "# trusted" not in line.lower()
                        and "# trust-verified" not in line.lower()
                    ):
                        results.append(
                            SecurityCheckResult(
                                name="pickle_deserialization",
                                severity=SecurityCheckSeverity.HIGH,
                                message="Pickle deserialization from potentially untrusted source",
                                file_path=str(py_file),
                                line_number=line_num,
                                recommendation="Use JSON or add # trust-verified comment if source is trusted",
                            )
                        )

            except (UnicodeDecodeError, PermissionError):
                continue

    except Exception as e:
        logger.warning("security_scan_error", error=str(e))

    return results


def run_security_audit(source_dir: str = "src") -> SecurityAuditReport:
    """Run full security audit at application startup.

    Args:
        source_dir: Directory to scan for code patterns.

    Returns:
        Security audit report.
    """
    logger.info("security_audit_starting")

    results = []

    # Check environment
    results.extend(check_env_security())

    # Check code patterns
    results.extend(check_code_patterns(source_dir))

    report = SecurityAuditReport(results=results)

    # Log results
    if report.passed:
        logger.info(
            "security_audit_passed",
            critical=report.critical_count,
            high=report.high_count,
            medium=report.medium_count,
        )
    else:
        logger.warning(
            "security_audit_failed",
            critical=report.critical_count,
            high=report.high_count,
            medium=report.medium_count,
            issues=[r.message for r in results if r.severity in ("CRITICAL", "HIGH")],
        )

    return report


__all__ = [
    "SecurityAuditReport",
    "SecurityCheckResult",
    "SecurityCheckSeverity",
    "check_code_patterns",
    "check_env_security",
    "run_security_audit",
]
