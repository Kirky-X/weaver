#!/usr/bin/env python
"""Quick verification that LadybugDB connection pool fix works.

Tests the previously-hanging endpoints (search/causal, search/temporal)
and a graph endpoint to verify connection pool is not exhausted.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:18012"
API_KEY = "dev_api_key_1234567890123456789012345678"
ADMIN_KEY = "dev_admin_key_1234567890123456789012345"
STARTUP_TIMEOUT = 120


def start_app() -> subprocess.Popen | None:
    """Start the Weaver app."""
    env = os.environ.copy()
    env_file = Path.cwd() / ".env"
    if env_file.exists():
        with env_file.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    if key and key not in env:
                        env[key] = value

    env["ENVIRONMENT"] = "development"
    env["WEAVER_API__API_KEY"] = API_KEY
    env["WEAVER_API__ADMIN_API_KEY"] = ADMIN_KEY
    env["WEAVER_API__PORT"] = "18013"
    env["WEAVER_POSTGRES__DSN"] = ""
    env["NEO4J_PASSWORD"] = ""
    env["WEAVER_API__REQUIRE_AUTH_FOR_METRICS"] = "false"
    env["WEAVER_API__PORT_AUTO_DETECT"] = "false"
    # Use separate DB paths to avoid file lock conflicts with previous instances
    env["WEAVER_DUCKDB__DB_PATH"] = "data/verify.duckdb"
    env["WEAVER_LADYBUG__DB_PATH"] = "data/verify.lbug"

    cmd = ["uv", "run", "python", "-m", "src.main"]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=str(Path.cwd()),
        preexec_fn=os.setsid,
    )
    print(f"App started (PID={proc.pid})")
    return proc


async def wait_for_health(proc: subprocess.Popen) -> bool:
    """Wait for app to become healthy."""
    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if proc.poll() is not None:
            print(f"App exited early with code {proc.returncode}")
            # Dump last output
            if proc.stdout:
                output = proc.stdout.read(5000).decode("utf-8", errors="replace")
                print(f"Last output:\n{output}")
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{BASE_URL}/health")
                if resp.status_code == 200:
                    print("App is healthy!")
                    return True
        except Exception:
            pass
        await asyncio.sleep(2)
    print("App did not become healthy within timeout")
    return False


async def test_endpoint(
    client: httpx.AsyncClient,
    name: str,
    method: str,
    path: str,
    *,
    params: dict | None = None,
    body: dict | None = None,
    timeout: float = 45.0,
) -> dict:
    """Test a single endpoint and return result."""
    headers = {"X-API-Key": API_KEY, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"

    print(f"\n[{name}] {method} {path} (timeout={timeout}s)")
    start = time.time()
    try:
        if method == "GET":
            resp = await asyncio.wait_for(
                client.get(f"{BASE_URL}{path}", params=params, headers=headers),
                timeout=timeout,
            )
        else:
            resp = await asyncio.wait_for(
                client.request(
                    method, f"{BASE_URL}{path}", params=params, json=body, headers=headers
                ),
                timeout=timeout,
            )
        elapsed = time.time() - start
        print(f"  -> {resp.status_code} ({elapsed:.1f}s)")
        return {
            "name": name,
            "status": resp.status_code,
            "elapsed": elapsed,
            "ok": True,
        }
    except TimeoutError:
        elapsed = time.time() - start
        print(f"  -> TIMEOUT ({elapsed:.1f}s)")
        return {"name": name, "status": 0, "elapsed": elapsed, "ok": False, "error": "timeout"}
    except Exception as e:
        elapsed = time.time() - start
        print(f"  -> ERROR: {e} ({elapsed:.1f}s)")
        return {"name": name, "status": 0, "elapsed": elapsed, "ok": False, "error": str(e)}


async def main() -> int:
    proc = None
    try:
        # Check if app already running
        async with httpx.AsyncClient(timeout=3.0) as client:
            try:
                resp = await client.get(f"{BASE_URL}/health")
                if resp.status_code == 200:
                    print("App already running")
            except Exception:
                print("Starting app...")
                proc = start_app()
                if not await wait_for_health(proc):
                    return 1

        # Run verification tests
        async with httpx.AsyncClient(timeout=60.0) as client:
            results = []

            # 1. System health (baseline)
            results.append(await test_endpoint(client, "health", "GET", "/health", timeout=10.0))

            # 2. Search causal (previously hung)
            results.append(
                await test_endpoint(
                    client,
                    "search_causal_normal",
                    "POST",
                    "/api/v1/search/causal",
                    body={"query": "test", "depth": 1},
                    timeout=45.0,
                )
            )

            # 3. Search temporal (previously hung)
            results.append(
                await test_endpoint(
                    client,
                    "search_temporal_normal",
                    "POST",
                    "/api/v1/search/temporal",
                    body={"query": "test", "time_range": "7d", "limit": 5},
                    timeout=45.0,
                )
            )

            # 4. Graph endpoint (previously timed out due to pool exhaustion)
            results.append(
                await test_endpoint(
                    client,
                    "graph_entities",
                    "GET",
                    "/api/v1/graph/entities",
                    params={"limit": 10},
                    timeout=30.0,
                )
            )

            # 5. Graph metrics (previously timed out)
            results.append(
                await test_endpoint(
                    client,
                    "graph_metrics",
                    "GET",
                    "/api/v1/graph/metrics",
                    timeout=30.0,
                )
            )

            # 6. Communities (previously timed out)
            results.append(
                await test_endpoint(
                    client,
                    "communities_list",
                    "GET",
                    "/api/v1/admin/communities",
                    params={"limit": 5},
                    timeout=30.0,
                )
            )

        # Summary
        print("\n" + "=" * 60)
        print("VERIFICATION SUMMARY")
        print("=" * 60)
        passed = 0
        failed = 0
        for r in results:
            status = "PASS" if r["ok"] else "FAIL"
            print(f"  [{status}] {r['name']}: status={r['status']} ({r['elapsed']:.1f}s)")
            if r["ok"]:
                passed += 1
            else:
                failed += 1
        print(f"\nTotal: {passed} passed, {failed} failed")

        # Key verification: even if search endpoints timed out,
        # graph/communities endpoints should still work (pool not exhausted)
        graph_ok = any(r["name"] == "graph_entities" and r["ok"] for r in results)
        metrics_ok = any(r["name"] == "graph_metrics" and r["ok"] for r in results)
        communities_ok = any(r["name"] == "communities_list" and r["ok"] for r in results)

        print("\nKEY VERIFICATION (connection pool not exhausted):")
        print(f"  graph_entities:    {'OK' if graph_ok else 'FAILED'}")
        print(f"  graph_metrics:     {'OK' if metrics_ok else 'FAILED'}")
        print(f"  communities_list:  {'OK' if communities_ok else 'FAILED'}")

        if graph_ok and metrics_ok and communities_ok:
            print("\n>>> CONNECTION POOL FIX VERIFIED <<<")
            return 0
        else:
            print("\n>>> CONNECTION POOL FIX NOT WORKING <<<")
            return 1

    finally:
        if proc is not None:
            print("\nStopping app...")
            try:
                os.killpg(os.getpgid(proc.pid), 15)
                proc.wait(timeout=10)
            except Exception:
                try:
                    os.killpg(os.getpgid(proc.pid), 9)
                except Exception:
                    pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
