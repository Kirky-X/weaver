# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X


"""Regression tests for the processing package facade."""

from __future__ import annotations

import inspect

import modules.processing as processing_pkg


class TestT008LowFixes:
    """Regression tests for LOW findings."""

    def test_pipeline_imported_from_package(self):
        """#239: re-export goes through the package, not the ``graph`` module."""
        src = inspect.getsource(processing_pkg)
        assert "from modules.processing.pipeline import Pipeline" in src

        from modules.processing.pipeline import Pipeline as PackagePipeline

        assert processing_pkg.Pipeline is PackagePipeline
