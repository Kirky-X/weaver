#!/usr/bin/env python
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Test Quality Monitoring Script.

Generates comprehensive test quality reports including:
- Test execution time analysis
- Coverage trends
- Test failure rates
- Slow test identification

Usage:
    uv run python tests/scripts/test_quality_monitor.py [--output-dir ./reports]

Output:
    - test_quality_report.json: Machine-readable report
    - test_quality_report.md: Human-readable summary
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@dataclass
class TestMetrics:
    """Test execution metrics."""

    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    coverage_percent: float = 0.0
    slow_tests: list[dict[str, Any]] = field(default_factory=list)
    test_files: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CoverageMetrics:
    """Coverage analysis metrics."""

    total_lines: int = 0
    covered_lines: int = 0
    branch_total: int = 0
    branch_covered: int = 0
    missing_modules: list[str] = field(default_factory=list)
    low_coverage_modules: list[dict[str, Any]] = field(default_factory=list)


def run_pytest_with_timing(output_dir: Path) -> tuple[TestMetrics, str]:
    """Run pytest and capture timing information.

    Returns:
        Tuple of (metrics, raw_output).
    """
    print("Running pytest with timing analysis...")

    # Run pytest with JSON report
    json_report = output_dir / "pytest_report.json"

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/",
        "--json-report",
        f"--json-report-file={json_report}",
        "--cov=src",
        "--cov-report=json",
        f"--cov-report=term-missing:output-file={output_dir / 'coverage.txt'}",
        "--durations=20",  # Show 20 slowest tests
        "-q",
        "--tb=no",
    ]

    result = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent.parent,
    )

    # Parse output
    metrics = TestMetrics()
    output = result.stdout + result.stderr

    # Parse pytest summary
    summary_match = re.search(
        r"(\d+) passed.*?(\d+) failed.*?(\d+) skipped.*?(\d+) error",
        output,
        re.IGNORECASE,
    )
    if summary_match:
        metrics.passed = int(summary_match.group(1))
        metrics.failed = int(summary_match.group(2))
        metrics.skipped = int(summary_match.group(3))
        metrics.errors = int(summary_match.group(4))
        metrics.total_tests = metrics.passed + metrics.failed + metrics.skipped + metrics.errors

    # Parse duration
    duration_match = re.search(r"in ([\d.]+)s", output)
    if duration_match:
        metrics.duration_seconds = float(duration_match.group(1))

    # Parse slow tests from output
    slow_section = False
    for line in output.split("\n"):
        if "slowest durations" in line.lower():
            slow_section = True
            continue
        if slow_section and line.strip():
            # Parse lines like: "0.45s call     tests/unit/test_foo.py::test_bar"
            match = re.match(r"([\d.]+)s\s+(call|setup|teardown)\s+(.+)", line.strip())
            if match:
                metrics.slow_tests.append(
                    {
                        "duration_seconds": float(match.group(1)),
                        "phase": match.group(2),
                        "test": match.group(3),
                    }
                )
            elif not line.startswith("="):
                break

    # Parse JSON report if available
    if json_report.exists():
        try:
            with open(json_report) as f:
                report_data = json.load(f)
                metrics.test_files = _parse_test_files(report_data)
        except Exception as e:
            print(f"Warning: Could not parse JSON report: {e}")

    return metrics, output


def _parse_test_files(report_data: dict) -> list[dict[str, Any]]:
    """Parse test file information from pytest JSON report."""
    test_files = []

    for test in report_data.get("tests", []):
        nodeid = test.get("nodeid", "")
        # Extract file path
        file_match = re.match(r"(tests/[^:]+\.py)", nodeid)
        if file_match:
            file_path = file_match.group(1)
            # Find or create file entry
            file_entry = next((f for f in test_files if f["path"] == file_path), None)
            if not file_entry:
                file_entry = {
                    "path": file_path,
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "duration": 0.0,
                }
                test_files.append(file_entry)

            file_entry["total"] += 1
            outcome = test.get("outcome", "unknown")
            if outcome == "passed":
                file_entry["passed"] += 1
            elif outcome == "failed":
                file_entry["failed"] += 1
            elif outcome == "skipped":
                file_entry["skipped"] += 1

            # Add duration
            duration = test.get("duration", 0)
            if duration:
                file_entry["duration"] += duration

    return test_files


def parse_coverage_report(output_dir: Path) -> CoverageMetrics:
    """Parse coverage.json and extract metrics."""
    coverage_file = output_dir.parent / "coverage.json"

    if not coverage_file.exists():
        # Try alternative location
        coverage_file = Path("coverage.json")

    metrics = CoverageMetrics()

    if not coverage_file.exists():
        print("Warning: coverage.json not found")
        return metrics

    try:
        with open(coverage_file) as f:
            data = json.load(f)

        totals = data.get("totals", {})
        metrics.total_lines = totals.get("num_statements", 0)
        metrics.covered_lines = totals.get("covered_lines", 0)
        metrics.branch_total = totals.get("num_branches", 0)
        metrics.branch_covered = totals.get("covered_branches", 0)

        # Find low coverage modules
        files = data.get("files", {})
        for file_path, file_data in files.items():
            summary = file_data.get("summary", {})
            percent = summary.get("percent_covered", 0)
            if percent < 80:
                metrics.low_coverage_modules.append(
                    {
                        "path": file_path,
                        "coverage_percent": percent,
                        "missing_lines": summary.get("missing_lines", 0),
                    }
                )

    except Exception as e:
        print(f"Warning: Could not parse coverage report: {e}")

    return metrics


def generate_report(
    test_metrics: TestMetrics,
    coverage_metrics: CoverageMetrics,
    output_dir: Path,
) -> dict[str, Any]:
    """Generate comprehensive quality report."""
    timestamp = datetime.now().isoformat()

    report = {
        "timestamp": timestamp,
        "test_metrics": {
            "total_tests": test_metrics.total_tests,
            "passed": test_metrics.passed,
            "failed": test_metrics.failed,
            "skipped": test_metrics.skipped,
            "errors": test_metrics.errors,
            "duration_seconds": round(test_metrics.duration_seconds, 2),
            "pass_rate": (
                round(test_metrics.passed / test_metrics.total_tests * 100, 2)
                if test_metrics.total_tests > 0
                else 0
            ),
            "slow_tests": test_metrics.slow_tests[:20],  # Top 20 slowest
            "test_files": test_metrics.test_files,
        },
        "coverage_metrics": {
            "line_coverage_percent": (
                round(
                    coverage_metrics.covered_lines / coverage_metrics.total_lines * 100,
                    2,
                )
                if coverage_metrics.total_lines > 0
                else 0
            ),
            "branch_coverage_percent": (
                round(
                    coverage_metrics.branch_covered / coverage_metrics.branch_total * 100,
                    2,
                )
                if coverage_metrics.branch_total > 0
                else 0
            ),
            "total_lines": coverage_metrics.total_lines,
            "covered_lines": coverage_metrics.covered_lines,
            "low_coverage_modules": sorted(
                coverage_metrics.low_coverage_modules,
                key=lambda x: x["coverage_percent"],
            )[:20],
        },
    }

    # Save JSON report
    json_path = output_dir / "test_quality_report.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"JSON report saved to: {json_path}")

    # Generate markdown summary
    md_path = output_dir / "test_quality_report.md"
    _generate_markdown_report(report, md_path)
    print(f"Markdown report saved to: {md_path}")

    return report


def _generate_markdown_report(report: dict[str, Any], output_path: Path) -> None:
    """Generate human-readable markdown report."""
    test = report["test_metrics"]
    cov = report["coverage_metrics"]

    lines = [
        "# Test Quality Report",
        "",
        f"**Generated**: {report['timestamp']}",
        "",
        "## Test Execution Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Tests | {test['total_tests']} |",
        f"| Passed | {test['passed']} |",
        f"| Failed | {test['failed']} |",
        f"| Skipped | {test['skipped']} |",
        f"| Errors | {test['errors']} |",
        f"| Pass Rate | {test['pass_rate']}% |",
        f"| Duration | {test['duration_seconds']}s |",
        "",
        "## Coverage Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Line Coverage | {cov['line_coverage_percent']}% |",
        f"| Branch Coverage | {cov['branch_coverage_percent']}% |",
        f"| Total Lines | {cov['total_lines']} |",
        f"| Covered Lines | {cov['covered_lines']} |",
        "",
    ]

    # Slow tests section
    if test["slow_tests"]:
        lines.extend(
            [
                "## Slowest Tests (Top 10)",
                "",
                "| Duration | Phase | Test |",
                "|----------|-------|------|",
            ]
        )
        for slow in test["slow_tests"][:10]:
            lines.append(f"| {slow['duration_seconds']:.2f}s | {slow['phase']} | {slow['test']} |")
        lines.append("")

    # Low coverage modules
    if cov["low_coverage_modules"]:
        lines.extend(
            [
                "## Low Coverage Modules (< 80%)",
                "",
                "| Module | Coverage | Missing Lines |",
                "|--------|----------|---------------|",
            ]
        )
        for module in cov["low_coverage_modules"][:10]:
            lines.append(
                f"| {module['path']} | {module['coverage_percent']:.1f}% | {module['missing_lines']} |"
            )
        lines.append("")

    # Recommendations
    lines.extend(
        [
            "## Recommendations",
            "",
        ]
    )

    if test["failed"] > 0:
        lines.append(f"- **Fix failing tests**: {test['failed']} tests are failing")

    if test["slow_tests"] and test["slow_tests"][0]["duration_seconds"] > 5:
        lines.append(
            f"- **Optimize slow tests**: Slowest test takes {test['slow_tests'][0]['duration_seconds']:.1f}s"
        )

    if cov["line_coverage_percent"] < 80:
        lines.append(
            f"- **Improve coverage**: Current {cov['line_coverage_percent']:.1f}% < 80% target"
        )

    if cov["low_coverage_modules"]:
        lines.append(
            f"- **Focus on low coverage modules**: {len(cov['low_coverage_modules'])} modules below 80%"
        )

    if not any(
        [
            test["failed"] > 0,
            test["slow_tests"] and test["slow_tests"][0]["duration_seconds"] > 5,
            cov["line_coverage_percent"] < 80,
            cov["low_coverage_modules"],
        ]
    ):
        lines.append("- All quality metrics are within acceptable ranges")

    lines.append("")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))


def main() -> int:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Test Quality Monitor")
    parser.add_argument(
        "--output-dir",
        default="reports/test_quality",
        help="Output directory for reports",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("Test Quality Monitor")
    print("=" * 70)

    # Run tests and collect metrics
    test_metrics, raw_output = run_pytest_with_timing(output_dir)

    # Parse coverage
    coverage_metrics = parse_coverage_report(output_dir)

    # Generate report
    report = generate_report(test_metrics, coverage_metrics, output_dir)

    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Tests: {test_metrics.total_tests} total, {test_metrics.passed} passed")
    print(f"Duration: {test_metrics.duration_seconds:.1f}s")
    print(f"Coverage: {coverage_metrics.covered_lines}/{coverage_metrics.total_lines} lines")
    print("=" * 70)

    return 0 if test_metrics.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
