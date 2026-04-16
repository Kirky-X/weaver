# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for core.security.audit module."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core.security.audit import (
    SecurityAuditReport,
    SecurityCheckResult,
    SecurityCheckSeverity,
    check_code_patterns,
    check_env_security,
    run_security_audit,
)


class TestSecurityCheckResult:
    """Test SecurityCheckResult dataclass."""

    def test_create_result(self):
        """Test creating SecurityCheckResult."""
        result = SecurityCheckResult(
            name="test_check",
            severity=SecurityCheckSeverity.HIGH,
            message="Test issue found",
        )

        assert result.name == "test_check"
        assert result.severity == SecurityCheckSeverity.HIGH
        assert result.message == "Test issue found"
        assert result.file_path is None

    def test_create_result_with_file(self):
        """Test creating result with file info."""
        result = SecurityCheckResult(
            name="sql_injection",
            severity=SecurityCheckSeverity.CRITICAL,
            message="SQL injection risk",
            file_path="src/test.py",
            line_number=42,
            recommendation="Use parameterized queries",
        )

        assert result.file_path == "src/test.py"
        assert result.line_number == 42
        assert result.recommendation == "Use parameterized queries"


class TestSecurityAuditReport:
    """Test SecurityAuditReport dataclass."""

    def test_empty_report_passes(self):
        """Test empty report passes."""
        report = SecurityAuditReport()

        assert report.passed is True
        assert report.critical_count == 0
        assert report.high_count == 0
        assert report.medium_count == 0

    def test_report_with_critical_fails(self):
        """Test report with CRITICAL issue fails."""
        report = SecurityAuditReport(
            results=[
                SecurityCheckResult(
                    name="critical_issue",
                    severity=SecurityCheckSeverity.CRITICAL,
                    message="Critical issue",
                )
            ]
        )

        assert report.passed is False
        assert report.critical_count == 1

    def test_report_with_high_fails(self):
        """Test report with HIGH issue fails."""
        report = SecurityAuditReport(
            results=[
                SecurityCheckResult(
                    name="high_issue",
                    severity=SecurityCheckSeverity.HIGH,
                    message="High issue",
                )
            ]
        )

        assert report.passed is False
        assert report.high_count == 1

    def test_report_with_medium_passes(self):
        """Test report with MEDIUM issue passes."""
        report = SecurityAuditReport(
            results=[
                SecurityCheckResult(
                    name="medium_issue",
                    severity=SecurityCheckSeverity.MEDIUM,
                    message="Medium issue",
                )
            ]
        )

        assert report.passed is True
        assert report.medium_count == 1

    def test_report_counts_multiple_issues(self):
        """Test report counts multiple issues."""
        report = SecurityAuditReport(
            results=[
                SecurityCheckResult("a", SecurityCheckSeverity.HIGH, "a"),
                SecurityCheckResult("b", SecurityCheckSeverity.HIGH, "b"),
                SecurityCheckResult("c", SecurityCheckSeverity.MEDIUM, "c"),
            ]
        )

        assert report.high_count == 2
        assert report.medium_count == 1


class TestCheckEnvSecurity:
    """Test check_env_security function."""

    def test_missing_env_vars(self):
        """Test detection of missing security env vars."""
        with patch.dict(os.environ, {}, clear=True):
            results = check_env_security()

            # Should detect missing env vars
            assert len(results) >= 1

    def test_development_mode_detected(self):
        """Test detection of development mode."""
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=True):
            results = check_env_security()

            # Should have development mode warning
            dev_result = next((r for r in results if r.name == "development_mode"), None)
            assert dev_result is not None
            assert dev_result.severity == SecurityCheckSeverity.INFO


class TestCheckCodePatterns:
    """Test check_code_patterns function."""

    def test_no_issues_in_clean_code(self, tmp_path):
        """Test clean code has no issues."""
        # Create a clean Python file
        clean_file = tmp_path / "clean.py"
        clean_file.write_text("""
def clean_function():
    query = "SELECT * FROM users WHERE id = $1"
    return query
""")

        results = check_code_patterns(str(tmp_path))

        # Should have no issues (parameterized query)
        sql_issues = [r for r in results if r.name == "sql_injection_risk"]
        assert len(sql_issues) == 0

    def test_detects_sql_fstring_injection(self, tmp_path):
        """Test detection of SQL f-string injection."""
        risky_file = tmp_path / "risky.py"
        risky_file.write_text("""
def risky_function(user_id):
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return query
""")

        results = check_code_patterns(str(tmp_path))

        # Should detect SQL injection risk
        sql_issues = [r for r in results if r.name == "sql_injection_risk"]
        assert len(sql_issues) >= 1

    def test_detects_cypher_fstring_injection(self, tmp_path):
        """Test detection of Cypher f-string injection."""
        risky_file = tmp_path / "risky.py"
        risky_file.write_text("""
def risky_function(name):
    query = f"MATCH (n:Entity {{name: '{name}'}}) RETURN n"
    return query
""")

        results = check_code_patterns(str(tmp_path))

        # Should detect Cypher injection risk
        cypher_issues = [r for r in results if r.name == "cypher_injection_risk"]
        assert len(cypher_issues) >= 1

    def test_detects_pickle_load(self, tmp_path):
        """Test detection of pickle.load usage."""
        risky_file = tmp_path / "risky.py"
        risky_file.write_text("""
import pickle

def load_data(file):
    with open(file, 'rb') as f:
        return pickle.load(f)
""")

        results = check_code_patterns(str(tmp_path))

        # Should detect pickle deserialization
        pickle_issues = [r for r in results if r.name == "pickle_deserialization"]
        assert len(pickle_issues) >= 1


class TestRunSecurityAudit:
    """Test run_security_audit function."""

    def test_runs_all_checks(self):
        """Test run_security_audit runs all checks."""
        with patch.dict(os.environ, {}, clear=True):
            report = run_security_audit(source_dir="src")

            assert isinstance(report, SecurityAuditReport)
            assert report.results is not None

    def test_returns_report(self):
        """Test run_security_audit returns report."""
        report = run_security_audit(source_dir="src")

        assert isinstance(report, SecurityAuditReport)


class TestSecurityCheckSeverity:
    """Test SecurityCheckSeverity enum."""

    def test_all_severities(self):
        """Test all severity levels exist."""
        assert SecurityCheckSeverity.CRITICAL.value == "CRITICAL"
        assert SecurityCheckSeverity.HIGH.value == "HIGH"
        assert SecurityCheckSeverity.MEDIUM.value == "MEDIUM"
        assert SecurityCheckSeverity.LOW.value == "LOW"
        assert SecurityCheckSeverity.INFO.value == "INFO"
