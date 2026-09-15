# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors


"""Regression tests for memory publisher dispatch (T008 #259)."""

from __future__ import annotations

import inspect

from modules.processing.pipeline.memory_publisher import MemoryEventPublisher


class TestT008LowFixes:
    """Regression tests for T008 LOW findings (#259)."""

    def test_zip_is_strict(self):
        """#259: events/results pairing uses ``strict=True``."""
        src = inspect.getsource(MemoryEventPublisher)

        assert "zip(events, results, strict=True)" in src
