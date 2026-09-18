# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for the shared committed-TOML data reader used by the vocabulary loaders."""

from pathlib import Path

from core.utils.toml_loader import load_toml_or_warn


def test_returns_parsed_mapping_for_valid_file(tmp_path: Path) -> None:
    """A well-formed TOML file is returned as a dict."""
    path = tmp_path / "data.toml"
    path.write_text('[aliases]\nfoo = "bar"\n', encoding="utf-8")

    data = load_toml_or_warn(path, event="probe")

    assert data == {"aliases": {"foo": "bar"}}


def test_missing_file_returns_empty_dict(tmp_path: Path) -> None:
    """A missing data file degrades to {} instead of raising (defensive loaders)."""
    data = load_toml_or_warn(tmp_path / "absent.toml", event="probe")

    assert data == {}


def test_malformed_toml_returns_empty_dict(tmp_path: Path) -> None:
    """Invalid TOML degrades to {} instead of crashing the importing module."""
    path = tmp_path / "bad.toml"
    path.write_text("this is = = not valid toml\n", encoding="utf-8")

    data = load_toml_or_warn(path, event="probe")

    assert data == {}
