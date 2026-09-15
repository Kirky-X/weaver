# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors


"""Regression tests for the processing package facade (T008 #239)."""

from __future__ import annotations

import inspect

import modules.processing as processing_pkg


class TestT008LowFixes:
    """Regression tests for T008 LOW findings (#239)."""

    def test_pipeline_imported_from_package(self):
        """#239: re-export goes through the package, not the ``graph`` module."""
        src = inspect.getsource(processing_pkg)
        assert "from modules.processing.pipeline import Pipeline" in src

        from modules.processing.pipeline import Pipeline as PackagePipeline

        assert processing_pkg.Pipeline is PackagePipeline
