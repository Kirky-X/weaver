#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

"""Test LadybugDB timeout mechanism."""

import asyncio
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.db.ladybug_pool import LadybugPool


async def test_timeout():
    """Test that LadybugDB query timeout works."""
    pool = LadybugPool(db_path="data/test_timeout.lbug")
    await pool.startup()
    print(f"Pool started. ASYNC_QUERY_TIMEOUT_SECONDS={pool.ASYNC_QUERY_TIMEOUT_SECONDS}")

    # Execute a simple query
    start = time.monotonic()
    try:
        result = await pool.execute_query("MATCH (n) RETURN count(n) as count")
        elapsed = time.monotonic() - start
        print(f"Simple query: {result} in {elapsed:.3f}s")
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"Simple query failed: {e} in {elapsed:.3f}s")

    # Execute a query that might hang (infinite loop in Cypher)
    start = time.monotonic()
    try:
        # This query might hang if there are cycles in the graph
        result = await pool.execute_query("MATCH (n)-[*1..10]->(m) RETURN n, m LIMIT 100")
        elapsed = time.monotonic() - start
        print(f"Traversal query: {len(result)} rows in {elapsed:.3f}s")
    except TimeoutError as e:
        elapsed = time.monotonic() - start
        print(f"Traversal query timed out in {elapsed:.3f}s: {e}")
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"Traversal query failed: {type(e).__name__}: {e} in {elapsed:.3f}s")

    # Check if event loop is still responsive
    start = time.monotonic()
    await asyncio.sleep(0.1)
    elapsed = time.monotonic() - start
    print(f"Event loop responsiveness: asyncio.sleep(0.1) took {elapsed:.3f}s")

    # Try another simple query
    start = time.monotonic()
    try:
        result = await pool.execute_query("MATCH (n) RETURN count(n) as count")
        elapsed = time.monotonic() - start
        print(f"Post-timeout simple query: {result} in {elapsed:.3f}s")
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"Post-timeout simple query failed: {e} in {elapsed:.3f}s")

    await pool.shutdown()
    print("Pool shut down.")


if __name__ == "__main__":
    asyncio.run(test_timeout())
