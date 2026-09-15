# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Centralized path constants for Weaver project.

All project-internal paths MUST be derived from PROJECT_ROOT.
No module should compute its own _PROJECT_ROOT variable.
"""

from __future__ import annotations

from pathlib import Path

# Project root directory (paths.py is in src/core/utils/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Standard project directories.
# NOTE: CONFIG_DIR / CACHE_DIR are part of the public path API (import them
# from here rather than re-deriving paths); they are intentionally kept even
# though no in-repo module imports them yet (OCR LOW #13).
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
CACHE_DIR = DATA_DIR / ".cache"


def data_path(filename: str) -> str:
    """Return absolute path to a file in the data directory.

    Traversal guard: ``filename`` must stay inside DATA_DIR, so a
    misconfigured value like ``"../config/llm.toml"`` fails fast instead of
    silently reading/writing outside the data directory. All current callers
    pass module-level constants, so this is defense in depth.

    Args:
        filename: Name of the file (e.g. "weaver.duckdb").

    Returns:
        Absolute path string.

    Raises:
        ValueError: If the resolved path escapes DATA_DIR.
    """
    resolved = (DATA_DIR / filename).resolve()
    if not resolved.is_relative_to(DATA_DIR.resolve()):
        raise ValueError(f"data_path() escapes the data directory: {filename!r}")
    return str(resolved)
