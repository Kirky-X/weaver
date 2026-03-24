#!/usr/bin/env python3
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Check for prohibited logging module usage.

This script enforces the use of loguru instead of the standard logging module.
It scans Python files for prohibited patterns like logging.getLogger(),
logging.info(), etc.

Exit codes:
    0: No violations found
    1: Violations found
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Patterns that indicate prohibited logging usage
PROHIBITED_PATTERNS = [
    # logging.getLogger() - most common violation
    (
        r"logging\.getLogger\s*\(",
        "logging.getLogger() - use get_logger() from core.observability.logging",
    ),
    # Direct logging calls
    (
        r"logging\.(debug|info|warning|error|critical|exception)\s*\(",
        "logging.{level}() - use loguru's log.{level}() instead",
    ),
    # logging.basicConfig
    (r"logging\.basicConfig\s*\(", "logging.basicConfig() - use loguru configuration instead"),
    # logging.FileHandler, StreamHandler, etc.
    (
        r"logging\.(FileHandler|StreamHandler|Handler)\s*\(",
        "logging handlers - use loguru's file output instead",
    ),
]

# Files/patterns to exclude from checking
EXCLUDE_PATTERNS = [
    r"__pycache__",
    r"\.venv",
    r"venv",
    r"\.git",
    r"site-packages",
    r"check_logging_usage\.py$",  # Exclude this script itself
    r"logging\.py$",  # Exclude the logging configuration module
]


def should_check_file(file_path: Path) -> bool:
    """Check if a file should be scanned.

    Args:
        file_path: Path to the file.

    Returns:
        True if the file should be checked.
    """
    file_str = str(file_path)

    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, file_str):
            return False

    return file_path.suffix == ".py"


def check_file(file_path: Path) -> list[tuple[int, str, str]]:
    """Check a single file for prohibited logging usage.

    Args:
        file_path: Path to the file to check.

    Returns:
        List of (line_number, line_content, message) tuples for violations.
    """
    violations = []

    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines()

        for i, line in enumerate(lines, start=1):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            # Check each prohibited pattern
            for pattern, message in PROHIBITED_PATTERNS:
                if re.search(pattern, line):
                    violations.append((i, line.strip(), message))
                    break  # Only report one violation per line

    except Exception as e:
        print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)

    return violations


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Check for prohibited logging module usage")
    parser.add_argument(
        "files",
        nargs="*",
        help="Files or directories to check (default: src/ tests/ scripts/)",
    )
    parser.add_argument(
        "--fix-hint",
        action="store_true",
        help="Print fix hints for violations",
    )

    args = parser.parse_args()

    # Determine paths to check
    if args.files:
        paths = [Path(f) for f in args.files]
    else:
        paths = [Path("src"), Path("tests"), Path("scripts")]

    # Collect all Python files
    all_files = []
    for path in paths:
        if path.is_file():
            if should_check_file(path):
                all_files.append(path)
        elif path.is_dir():
            for py_file in path.rglob("*.py"):
                if should_check_file(py_file):
                    all_files.append(py_file)

    # Check all files
    total_violations = 0
    for file_path in all_files:
        violations = check_file(file_path)

        if violations:
            total_violations += len(violations)
            print(f"\n❌ {file_path}")

            for line_num, line_content, message in violations:
                print(f"  Line {line_num}: {message}")
                print(f"    {line_content}")

                if args.fix_hint:
                    print(f"    → Replace with: from core.observability.logging import get_logger")
                    print(f"    → Then use: log = get_logger(__name__)")

    # Summary
    if total_violations > 0:
        print(f"\n❌ Found {total_violations} logging violation(s) in {len(all_files)} files")
        print("\n💡 Fix: Use loguru instead of logging module")
        print("   from core.observability.logging import get_logger")
        print("   log = get_logger(__name__)")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
