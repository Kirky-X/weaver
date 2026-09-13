# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for deep LLM config reference validation (T011)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from config.validation import ConfigReferenceError, validate_llm_references


def _provider(model_id: str = "") -> MagicMock:
    provider = MagicMock()
    provider.models = {"chat": MagicMock(model_id=model_id)}
    return provider


def _settings(call_points: dict, providers: dict) -> MagicMock:
    settings = MagicMock()
    settings.llm.call_points = call_points
    settings.llm.providers = providers
    return settings


class TestValidateLlmReferences:
    def test_valid_config_passes(self) -> None:
        routing = MagicMock(primary="chat.openai.gpt-4o", fallbacks=[])
        settings = _settings(
            {"classifier": routing}, {"openai": _provider(model_id="gpt-4o")}
        )

        warnings = validate_llm_references(settings)

        assert warnings == []

    def test_unknown_provider_raises_with_section_path(self) -> None:
        routing = MagicMock(primary="chat.agnes.agnes-2.0-flash", fallbacks=[])
        settings = _settings({"embedding": routing}, {"openai": _provider()})

        with pytest.raises(ConfigReferenceError) as exc_info:
            validate_llm_references(settings)

        message = str(exc_info.value)
        assert "[call-points.embedding].primary" in message
        assert "agnes" in message
        assert "openai" in message  # lists defined providers

    def test_placeholder_primary_raises(self) -> None:
        routing = MagicMock(primary="your_embedding_provider", fallbacks=[])
        settings = _settings({"embedding": routing}, {"openai": _provider()})

        with pytest.raises(ConfigReferenceError, match="placeholder or empty"):
            validate_llm_references(settings)

    def test_placeholder_in_fallbacks_raises(self) -> None:
        routing = MagicMock(
            primary="chat.openai.gpt-4o", fallbacks=["changeme"]
        )
        settings = _settings({"classifier": routing}, {"openai": _provider()})

        with pytest.raises(ConfigReferenceError, match="fallbacks\\[0\\]"):
            validate_llm_references(settings)

    def test_malformed_label_raises(self) -> None:
        routing = MagicMock(primary="chat.openai", fallbacks=[])
        settings = _settings({"merger": routing}, {"openai": _provider()})

        with pytest.raises(ConfigReferenceError, match="malformed label"):
            validate_llm_references(settings)

    def test_missing_model_type_raises(self) -> None:
        routing = MagicMock(primary="embedding.openai.text-embedding-3-large", fallbacks=[])
        settings = _settings({"embedding": routing}, {"openai": _provider()})

        with pytest.raises(ConfigReferenceError, match="models.embedding"):
            validate_llm_references(settings)

    def test_model_id_mismatch_is_warning_not_error(self) -> None:
        routing = MagicMock(primary="chat.openai.gpt-4o", fallbacks=[])
        settings = _settings(
            {"classifier": routing}, {"openai": _provider(model_id="gpt-3.5-turbo")}
        )

        warnings = validate_llm_references(settings)

        assert len(warnings) == 1
        assert "gpt-4o" in warnings[0]

    def test_non_dict_config_is_ignored(self) -> None:
        """Validation is a no-op for mock/partial settings objects."""
        settings = MagicMock()
        settings.llm.call_points = MagicMock()  # not a dict
        settings.llm.providers = MagicMock()

        assert validate_llm_references(settings) == []
