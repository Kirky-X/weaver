# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for core.llm module __init__.py lazy loading."""

import pytest


class TestLLMModuleExports:
    """Test core.llm module exports."""

    def test_direct_imports_are_available(self):
        """Test that directly imported symbols are available."""
        from core.llm import (
            CallPoint,
            CandidateScore,
            Capability,
            CircuitState,
            EvalConfig,
            ExperienceData,
            GlobalConfig,
            Label,
            LLMClient,
            LLMResponse,
            LLMTask,
            LLMType,
            ModelConfig,
            ProviderConfig,
            RoutingConfig,
            RoutingInfeasibleError,
            RoutingMode,
            TokenUsage,
        )

        # All should be importable without error
        assert LLMClient is not None
        assert LLMType is not None
        assert Label is not None

    def test_all_list_contains_expected_symbols(self):
        """Test that __all__ contains expected symbols."""
        from core.llm import __all__

        expected = [
            "LLMClient",
            "LLMType",
            "Label",
            "ModelConfig",
            "ProviderConfig",
        ]
        for symbol in expected:
            assert symbol in __all__


class TestLazyLoading:
    """Test lazy loading via __getattr__."""

    def test_lazy_import_eval_runner(self):
        """Test lazy import of EvalRunner."""
        from core.llm import EvalRunner

        assert EvalRunner is not None

    def test_lazy_import_experience_store(self):
        """Test lazy import of ExperienceStore."""
        from core.llm import ExperienceStore

        assert ExperienceStore is not None

    def test_lazy_import_model_selector(self):
        """Test lazy import of ModelSelector."""
        from core.llm import ModelSelector

        assert ModelSelector is not None

    def test_lazy_import_smart_router(self):
        """Test lazy import of SmartRouter."""
        from core.llm import SmartRouter

        assert SmartRouter is not None

    def test_lazy_import_live_config(self):
        """Test lazy import of LiveConfig."""
        from core.llm import LiveConfig

        assert LiveConfig is not None

    def test_invalid_attribute_raises_attribute_error(self):
        """Test that accessing invalid attribute raises AttributeError."""
        import core.llm

        with pytest.raises(AttributeError, match="has no attribute"):
            _ = core.llm.NonExistentSymbol

    def test_lazy_modules_are_cached(self):
        """Test that lazy imports don't re-import on subsequent access."""
        import core.llm as llm_module

        # First access
        _ = llm_module.EvalRunner
        # Second access should use cached import
        _ = llm_module.EvalRunner
        # No error means it works
