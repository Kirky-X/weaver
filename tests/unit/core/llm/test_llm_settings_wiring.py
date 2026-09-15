# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for LLMSettings wiring that was previously dead config surface.

Covers: provider-level ``request_delay_*`` forwarding (parse_providers used
to drop these keys), nullable provider ``timeout`` (an absent value must fall
back to ``[global].default_timeout`` at the pool instead of a hardcoded
120.0), and the ``[global]`` → top-level mapping for request-delay keys.

Every case injects an isolated TOML path so a developer's local
``config/llm.toml`` cannot flip assertions.
"""

from __future__ import annotations

from pathlib import Path

from core.llm.config.config import LLMSettings

_ABSENT = "absent.toml"


class TestProviderTimeoutFallback:
    def test_absent_timeout_is_none(self, tmp_path: Path) -> None:
        settings = LLMSettings(
            toml_path=tmp_path / _ABSENT, providers={"p": {"type": "openai", "api_key": ""}}
        )
        assert settings.providers["p"].timeout is None

    def test_explicit_timeout_kept(self, tmp_path: Path) -> None:
        settings = LLMSettings(
            toml_path=tmp_path / _ABSENT, providers={"p": {"type": "openai", "timeout": 300.0}}
        )
        assert settings.providers["p"].timeout == 300.0


class TestRequestDelayWiring:
    def test_global_defaults_disabled(self, tmp_path: Path) -> None:
        settings = LLMSettings(toml_path=tmp_path / _ABSENT, providers={})
        assert settings.request_delay_enabled is False
        assert settings.request_delay_min == 1.0
        assert settings.request_delay_max == 2.0

    def test_global_request_delay_mapped_from_toml(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "llm.toml"
        toml_file.write_text(
            "[global]\n"
            "request_delay_enabled = true\n"
            "request_delay_min = 0.2\n"
            "request_delay_max = 0.8\n",
            encoding="utf-8",
        )
        settings = LLMSettings(toml_path=toml_file)
        assert settings.request_delay_enabled is True
        assert settings.request_delay_min == 0.2
        assert settings.request_delay_max == 0.8

    def test_provider_request_delay_forwarded(self, tmp_path: Path) -> None:
        settings = LLMSettings(
            toml_path=tmp_path / _ABSENT,
            providers={
                "p": {
                    "type": "openai",
                    "request_delay_enabled": True,
                    "request_delay_min": 0.5,
                    "request_delay_max": 1.5,
                }
            },
        )
        provider = settings.providers["p"]
        assert provider.request_delay_enabled is True
        assert provider.request_delay_min == 0.5
        assert provider.request_delay_max == 1.5

    def test_provider_request_delay_absent_is_none(self, tmp_path: Path) -> None:
        settings = LLMSettings(
            toml_path=tmp_path / _ABSENT, providers={"p": {"type": "openai"}}
        )
        assert settings.providers["p"].request_delay_enabled is None
