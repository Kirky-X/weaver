# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for the settings.toml unknown-key detector.

Root Settings uses extra="ignore", so a typo'd TOML key would be silently
dropped; _unknown_toml_keys surfaces such keys at startup as warnings.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from config.settings import _unknown_toml_keys


class _Nested(BaseModel):
    known_key: int = 0


class _Inner(BaseModel):
    leaf: int = 0


class _Middle(BaseModel):
    inner: _Inner = _Inner()


class _Outer(BaseModel):
    middle: _Middle = _Middle()


class _OptionalRoot(BaseModel):
    maybe: _Nested | None = None


class _Root(BaseModel):
    section: _Nested = _Nested()
    scalar: str = "x"


def _write_toml(tmp_path: Path, content: str) -> Path:
    toml_file = tmp_path / "settings.toml"
    toml_file.write_text(content, encoding="utf-8")
    return toml_file


class TestUnknownTomlKeys:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert _unknown_toml_keys(tmp_path / "absent.toml", _Root) == []

    def test_known_keys_pass(self, tmp_path: Path) -> None:
        toml_file = _write_toml(tmp_path, 'scalar = "ok"\n\n[section]\nknown_key = 1\n')
        assert _unknown_toml_keys(toml_file, _Root) == []

    def test_unknown_top_level_section(self, tmp_path: Path) -> None:
        toml_file = _write_toml(tmp_path, "[vault]\nenabled = false\n")
        assert _unknown_toml_keys(toml_file, _Root) == [("<root>", "vault")]

    def test_unknown_key_inside_known_section(self, tmp_path: Path) -> None:
        toml_file = _write_toml(tmp_path, "[section]\ntypoed_key = 1\n")
        assert _unknown_toml_keys(toml_file, _Root) == [("section", "typoed_key")]

    def test_mixed_known_and_unknown(self, tmp_path: Path) -> None:
        toml_file = _write_toml(tmp_path, "[section]\nknown_key = 1\ntypoed = 2\n")
        assert _unknown_toml_keys(toml_file, _Root) == [("section", "typoed")]

    def test_two_level_nesting(self, tmp_path: Path) -> None:
        toml_file = _write_toml(tmp_path, "[middle.inner]\ntypo = 1\n")
        assert _unknown_toml_keys(toml_file, _Outer) == [("middle.inner", "typo")]

    def test_optional_annotation_still_checked(self, tmp_path: Path) -> None:
        toml_file = _write_toml(tmp_path, "[maybe]\ntypo = 1\n")
        assert _unknown_toml_keys(toml_file, _OptionalRoot) == [("maybe", "typo")]
