# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors


"""Regression tests for consistency job hardening (T008 #419, #421)."""

from __future__ import annotations

import inspect

from modules.scheduler import consistency_jobs as module


class TestT008LowFixes:
    """Regression tests for T008 LOW findings (#419, #421)."""

    def test_json_repair_is_no_longer_used(self):
        """#419: own serialized payloads are parsed with plain ``json.loads``."""
        source = inspect.getsource(module)

        assert "json_repair" not in source
        assert "task_status_invalid_json" in source

    def test_temp_keys_without_entity_ids_is_reported(self):
        """#421: the skipped temp-key update path is surfaced to operators."""
        source = inspect.getsource(module)

        assert "sync_entity_temp_keys_without_entity_ids" in source
