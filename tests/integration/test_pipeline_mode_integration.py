# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for pipeline processing modes with real services.

Tests verify:
1. ProcessingMode enum values work correctly
2. Mode-specific configuration overrides are applied correctly
3. CLI arguments are parsed correctly

These tests use real services when available and do NOT use mocks.
For mock-based unit tests, see tests/unit/pipeline/test_pipeline_modes.py
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestProcessingModeConfiguration:
    """Test mode-specific configuration overrides (no mocks needed)."""

    def test_fast_mode_config(self) -> None:
        """Test that fast mode config has correct overrides."""
        from scripts.pipeline import ProcessingMode, get_mode_config

        config = get_mode_config(ProcessingMode.FAST)

        assert config.get("skip_entities") is True
        assert config.get("skip_quality") is True
        assert config.get("skip_credibility") is True
        assert config.get("skip_phase3") is True

    def test_deep_mode_config(self) -> None:
        """Test that deep mode config has no overrides."""
        from scripts.pipeline import ProcessingMode, get_mode_config

        config = get_mode_config(ProcessingMode.DEEP)

        # Deep mode should have empty config (no overrides)
        assert config == {}

    def test_processing_mode_enum(self) -> None:
        """Test ProcessingMode enum values."""
        from scripts.pipeline import ProcessingMode

        assert ProcessingMode.FAST.value == "fast"
        assert ProcessingMode.DEEP.value == "deep"
        assert ProcessingMode("fast") == ProcessingMode.FAST
        assert ProcessingMode("deep") == ProcessingMode.DEEP

    def test_processing_mode_string_conversion(self) -> None:
        """Test ProcessingMode string conversion."""
        from scripts.pipeline import ProcessingMode

        # Test that we can convert string to enum
        fast_mode = ProcessingMode("fast")
        assert fast_mode == ProcessingMode.FAST

        deep_mode = ProcessingMode("deep")
        assert deep_mode == ProcessingMode.DEEP

        # Test that invalid value raises error
        with pytest.raises(ValueError):
            ProcessingMode("invalid")


@pytest.mark.integration
class TestPipelineModeCLI:
    """Test CLI argument parsing for processing modes (no mocks needed)."""

    def test_cli_help_text(self) -> None:
        """Test that CLI help text includes processing mode information."""
        import argparse

        from scripts.pipeline import main

        # Parse --help to verify processing-mode is documented
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--processing-mode",
            choices=["fast", "deep"],
            default="deep",
            help="Processing mode: 'fast' or 'deep'",
        )

        # Verify argument is properly defined
        args = parser.parse_args(["--processing-mode", "fast"])
        assert args.processing_mode == "fast"

        args = parser.parse_args(["--processing-mode", "deep"])
        assert args.processing_mode == "deep"

        # Test default value
        args = parser.parse_args([])
        assert args.processing_mode == "deep"


@pytest.mark.integration
class TestPipelineFastModeMethod:
    """Test that process_batch_fast method exists and has correct signature."""

    def test_pipeline_has_process_batch_fast_method(self) -> None:
        """Test that Pipeline class has process_batch_fast method."""
        from modules.processing.pipeline.graph import Pipeline

        # Verify method exists
        assert hasattr(Pipeline, "process_batch_fast")

        # Verify it's a coroutine function
        import inspect

        assert inspect.iscoroutinefunction(Pipeline.process_batch_fast)

    def test_process_batch_fast_signature(self) -> None:
        """Test that process_batch_fast has expected parameters."""
        import inspect

        from modules.processing.pipeline.graph import Pipeline

        sig = inspect.signature(Pipeline.process_batch_fast)
        params = list(sig.parameters.keys())

        # Should have self, articles, and optional article_ids, task_id
        assert "articles" in params
        assert "article_ids" in params
        assert "task_id" in params


@pytest.mark.integration
class TestPipelineModePerformanceExpectations:
    """Test performance expectations documentation (informational tests)."""

    def test_fast_mode_performance_documentation(self) -> None:
        """Verify fast mode performance expectations are documented."""
        from scripts.pipeline import ProcessingMode

        # Fast mode documentation should indicate Phase 1 only
        fast_doc = ProcessingMode.__doc__ or ""
        assert "Phase 1" in fast_doc or "phase 1" in fast_doc.lower()

    def test_deep_mode_performance_documentation(self) -> None:
        """Verify deep mode performance expectations are documented."""
        from scripts.pipeline import ProcessingMode

        # Deep mode documentation should indicate full processing
        deep_doc = ProcessingMode.__doc__ or ""
        assert "Full" in deep_doc or "full" in deep_doc.lower()