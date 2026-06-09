# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Centralized path constants for Weaver project.

All project-internal paths MUST be derived from PROJECT_ROOT.
No module should compute its own _PROJECT_ROOT variable.
"""

from __future__ import annotations

from pathlib import Path

# Project root directory (paths.py is in src/core/utils/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Standard project directories
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
CACHE_DIR = DATA_DIR / ".cache"


def data_path(filename: str) -> str:
    """Return absolute path to a file in the data directory.

    Args:
        filename: Name of the file (e.g. "weaver.duckdb").

    Returns:
        Absolute path string.
    """
    return str(DATA_DIR / filename)
