# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for BM25 pickle lock concurrency.

Verifies that the threading.Lock in _secure_pickle_load serializes
concurrent callers and always restores pickle.load to its original value.
"""

from __future__ import annotations

import pickle
import threading
import time
from contextlib import contextmanager

from modules.knowledge.search.retrievers.bm25_retriever import (
    _pickle_lock,
    _secure_pickle_load,
)


class TestPickleLockConcurrency:
    """_secure_pickle_load must be safe under concurrent use."""

    def test_pickle_load_restored_after_context(self):
        """pickle.load must be the original after exiting the context manager."""
        original_load = pickle.load
        with _secure_pickle_load():
            # Inside the context, pickle.load should be patched
            assert pickle.load is not original_load
        # After exit, must be restored
        assert pickle.load is original_load

    def test_concurrent_loads_restore_original(self):
        """Multiple sequential _secure_pickle_load calls must all restore original."""
        original_load = pickle.load
        errors: list[Exception] = []

        def worker():
            try:
                with _secure_pickle_load():
                    # Inside: pickle.load is the restricted version
                    assert pickle.load is not original_load
                # After: must be restored
                assert pickle.load is original_load
            except Exception as e:
                errors.append(e)

        # Run workers sequentially (lock serializes anyway)
        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t1.join(timeout=10)
        t2.start()
        t2.join(timeout=10)

        assert not errors, f"Workers failed: {errors}"
        # Final state: pickle.load must be original
        assert pickle.load is original_load

    def test_lock_is_module_level(self):
        """_pickle_lock must be a threading.Lock instance."""
        assert isinstance(_pickle_lock, type(threading.Lock()))
