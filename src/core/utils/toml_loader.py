# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Shared reader for committed TOML *data* files (vocabularies / mappings).

These are not runtime *settings* (those go through pydantic-settings). They are
reference data — entity/category vocabularies and synonym maps — that we keep as
data files under ``config/`` instead of hardcoded literals in Python modules.

Callers treat a missing or malformed data file as a graceful degradation
(empty mapping) rather than a crash, because the consumers are defensive
post-processing steps. The failure is always surfaced as a WARNING so it is
never silent.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from core.observability import get_logger

_log = get_logger(__name__)


def load_toml_or_warn(path: Path, *, event: str) -> dict[str, Any]:
    """Load a committed TOML data file as a dict, returning ``{}`` on any failure.

    Args:
        path: Absolute path to the TOML data file.
        event: Stable log-event prefix. Three events are emitted as needed:
            ``<event>_missing`` (file absent), ``<event>_parse_failed``
            (invalid TOML) and ``<event>_read_failed`` (other OS errors).

    Returns:
        Parsed TOML mapping, or ``{}`` when the file cannot be read/parsed.
    """
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        _log.warning(f"{event}_missing", path=str(path))
        return {}
    except tomllib.TOMLDecodeError as exc:
        _log.warning(f"{event}_parse_failed", error=str(exc), path=str(path))
        return {}
    except OSError as exc:
        _log.warning(f"{event}_read_failed", error=str(exc), path=str(path))
        return {}
