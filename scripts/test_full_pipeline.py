#!/usr/bin/env python
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Full pipeline end-to-end test via HTTP API.

Tests the complete flow:
1. Start Weaver app (or connect to running instance)
2. Register 36kr source via NewsNow API
3. Trigger pipeline (max 5 items)
4. Poll task status until completion
5. Verify data in PostgreSQL and Neo4j

Usage:
    uv run python scripts/test_full_pipeline.py [--app-url http://localhost:8000] [--max-items 5]
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import time
from typing import Any

# Ensure src is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import httpx

# ─── Configuration ─────────────────────────────────────────────────────────────

DEFAULT_API_KEY = "dev-api-key-for-testing-purposes"
DEFAULT_APP_URL = "http://localhost:8000"
DEFAULT_MAX_ITEMS = 5
POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 120
API_TIMEOUT_SECONDS = 120

# Source configuration
SOURCE_ID = "36kr"
SOURCE_NAME = "36kr"
# Use newsnow.world (net.cn returns 502 Bad Gateway)
SOURCE_URL = "https://www.newsnow.world/api/s?id=36kr"
SOURCE_TYPE = "newsnow"


# ─── Color output ─────────────────────────────────────────────────────────────


class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    NC = "\033[0m"  # No Color


def log_info(msg: str) -> None:
    print(f"{Colors.GREEN}[INFO]{Colors.NC} {msg}")


def log_warn(msg: str) -> None:
    print(f"{Colors.YELLOW}[WARN]{Colors.NC} {msg}")


def log_error(msg: str) -> None:
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}")


def log_step(step: str, msg: str) -> None:
    print(f"{Colors.BLUE}[{step}]{Colors.NC} {msg}")


# ─── App process management ───────────────────────────────────────────────────

APP_ENV = {
    # Override settings.toml to match Docker Compose
    "WEAVER_POSTGRES__DSN": "postgresql+asyncpg://postgres:postgres@localhost:5432/weaver",
    # Neo4j password: must match NEO4J_AUTH in docker-compose.dev.yml (neo4j/password)
    # Also must match .env WEAVER_NEO4J__PASSWORD
    "NEO4J_PASSWORD": "password",
    # Load existing .env
    "POSTGRES_PASSWORD": os.getenv("POSTGRES_PASSWORD", "postgres"),
    "ENVIRONMENT": "development",
}


def start_app_process(project_root: str) -> subprocess.Popen[bytes]:
    """Start Weaver app as a background subprocess."""
    log_info("Starting Weaver app...")

    env = dict(os.environ)
    env.update(APP_ENV)

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "src.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]

    proc = subprocess.Popen(
        cmd,
        cwd=project_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,  # New process group
    )

    # Wait for app to be ready
    app_url = DEFAULT_APP_URL
    for attempt in range(30):
        try:
            resp = httpx.get(f"{app_url}/health", timeout=2.0)
            if resp.status_code in (200, 503):
                log_info(f"Weaver app ready at {app_url} (attempt {attempt + 1})")
                return proc
        except (httpx.ConnectError, httpx.ReadTimeout):
            pass
        time.sleep(2)

    # If we get here, app didn't start
    proc.terminate()
    stdout, stderr = proc.communicate(timeout=5)
    raise RuntimeError(
        f"Weaver app failed to start.\nSTDOUT:\n{stdout.decode(errors='replace')}\n\nSTDERR:\n{stderr.decode(errors='replace')}"
    )


def stop_app_process(proc: subprocess.Popen[bytes]) -> None:
    """Gracefully stop the Weaver app process."""
    log_info("Stopping Weaver app...")
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=10)
        log_info("Weaver app stopped.")
    except Exception as e:
        log_warn(f"Error stopping app: {e}")
        with contextlib.suppress(Exception):
            proc.terminate()


# ─── HTTP API helpers ─────────────────────────────────────────────────────────

_headers = {"X-API-Key": DEFAULT_API_KEY, "Content-Type": "application/json"}


def api_get(
    client: httpx.Client, path: str, timeout: float = API_TIMEOUT_SECONDS
) -> dict[str, Any]:
    """Send GET request to API."""
    resp = client.get(path, headers=_headers, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f"API GET {path} failed: {resp.status_code} {resp.text}")
    return resp.json()


def api_post(
    client: httpx.Client,
    path: str,
    data: dict[str, Any],
    timeout: float = API_TIMEOUT_SECONDS,
) -> httpx.Response:
    """Send POST request to API."""
    return client.post(path, headers=_headers, json=data, timeout=timeout)


# ─── Step 1: Register source ───────────────────────────────────────────────────


async def step_register_source(client: httpx.Client) -> bool:
    """Register the 36kr source. Returns True if already exists or registered."""
    log_step("1/4", f"Registering source '{SOURCE_ID}'...")

    payload = {
        "id": SOURCE_ID,
        "name": SOURCE_NAME,
        "url": SOURCE_URL,
        "source_type": SOURCE_TYPE,
        "enabled": True,
        "interval_minutes": 30,
    }

    resp = api_post(client, "/api/v1/sources", payload)

    if resp.status_code == 201:
        log_info(f"  ✓ Source '{SOURCE_ID}' registered (201)")
        return True
    elif resp.status_code == 409:
        log_info(f"  ✓ Source '{SOURCE_ID}' already exists (409)")
        return True
    else:
        log_error(f"  ✗ Failed to register source: {resp.status_code} {resp.text}")
        return False


# ─── Step 2: Trigger pipeline ─────────────────────────────────────────────────


async def step_trigger_pipeline(client: httpx.Client, max_items: int) -> str | None:
    """Trigger pipeline and return task_id."""
    log_step("2/4", f"Triggering pipeline (max_items={max_items})...")

    payload = {
        "source_id": SOURCE_ID,
        "max_items": max_items,
        "force": True,
    }

    resp = api_post(client, "/api/v1/pipeline/trigger", payload)

    if resp.status_code != 200:
        log_error(f"  ✗ Pipeline trigger failed: {resp.status_code} {resp.text}")
        return None

    data = resp.json()
    task_id = data.get("task_id")
    log_info(f"  ✓ Pipeline triggered, task_id={task_id}")
    return task_id


# ─── Step 3: Poll task status ─────────────────────────────────────────────────


async def step_poll_task(client: httpx.Client, task_id: str) -> dict[str, Any]:
    """Poll task status until completed, failed, or timeout."""
    log_step("3/4", f"Polling task status (task_id={task_id})...")

    deadline = time.time() + POLL_TIMEOUT_SECONDS

    while time.time() < deadline:
        data = api_get(client, f"/api/v1/pipeline/tasks/{task_id}")
        status = data.get("status", "unknown")

        completed = data.get("completed_count", 0)
        processing = data.get("processing_count", 0)
        failed = data.get("failed_count", 0)
        pending = data.get("pending_count", 0)

        print(
            f"  status={status} | completed={completed} processing={processing} "
            f"failed={failed} pending={pending}"
        )

        if status in ("completed", "failed"):
            log_info(f"  ✓ Task finished with status: {status}")
            return data

        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    log_error(f"  ✗ Polling timeout after {POLL_TIMEOUT_SECONDS}s")
    return api_get(client, f"/api/v1/pipeline/tasks/{task_id}")


# ─── Step 4: Verify results ───────────────────────────────────────────────────


async def step_verify_results(
    project_root: str,
) -> dict[str, Any]:
    """Query PostgreSQL and Neo4j to verify data was stored."""
    log_step("4/4", "Verifying database results...")

    results: dict[str, Any] = {}

    # PostgreSQL verification
    try:
        import asyncpg

        conn = await asyncpg.connect(
            host="localhost",
            port=5432,
            user="postgres",
            password="postgres",
            database="weaver",
            timeout=10,
        )
        try:
            # Count articles
            article_count = await conn.fetchval(
                "SELECT COUNT(*) FROM articles WHERE source_url IS NOT NULL AND source_url != ''"
            )
            results["pg_articles"] = article_count
            log_info(f"  ✓ PostgreSQL articles: {article_count}")

            # Count vectors
            vector_count = await conn.fetchval(
                "SELECT COUNT(*) FROM article_vectors WHERE embedding IS NOT NULL"
            )
            results["pg_vectors"] = vector_count
            log_info(f"  ✓ PostgreSQL article_vectors: {vector_count}")

            # Show sample titles
            rows = await conn.fetch(
                "SELECT id, title, persist_status FROM articles ORDER BY id DESC LIMIT 3"
            )
            if rows:
                log_info("  Recent articles:")
                for row in rows:
                    title = (row["title"] or "")[:60]
                    status = row["persist_status"]
                    print(f"    [{status}] {title}")
        finally:
            await conn.close()
    except Exception as e:
        log_warn(f"  ⚠ PostgreSQL verification failed: {e}")
        results["pg_error"] = str(e)

    # Neo4j verification
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
        with driver.session() as session:
            article_count = session.run("MATCH (a:Article) RETURN count(a) AS cnt").single()[0]
            results["neo4j_articles"] = article_count
            log_info(f"  ✓ Neo4j Article nodes: {article_count}")

            entity_count = session.run("MATCH (e:Entity) RETURN count(e) AS cnt").single()[0]
            results["neo4j_entities"] = entity_count
            log_info(f"  ✓ Neo4j Entity nodes: {entity_count}")

        driver.close()
    except Exception as e:
        log_warn(f"  ⚠ Neo4j verification failed: {e}")
        results["neo4j_error"] = str(e)

    return results


# ─── Main ─────────────────────────────────────────────────────────────────────


async def run_test(
    project_root: str,
    app_url: str,
    max_items: int,
    start_app: bool,
) -> int:
    """Run the full pipeline test. Returns 0 on success, 1 on failure."""

    print("=" * 70)
    print("Weaver Full Pipeline E2E Test")
    print("=" * 70)
    print(f"  App URL:   {app_url}")
    print(f"  Source:    {SOURCE_URL}")
    print(f"  Max items: {max_items}")
    print(f"  Start app: {start_app}")
    print("=" * 70)

    proc: subprocess.Popen[bytes] | None = None

    try:
        # Start app if requested
        if start_app:
            proc = start_app_process(project_root)

        # Wait briefly for app to fully initialize
        await asyncio.sleep(3)

        # Create HTTP client
        with httpx.Client(base_url=app_url, timeout=API_TIMEOUT_SECONDS) as client:

            # Step 1: Register source
            if not await step_register_source(client):
                return 1

            # Step 2: Trigger pipeline
            task_id = await step_trigger_pipeline(client, max_items)
            if not task_id:
                return 1

            # Step 3: Poll until done
            task_result = await step_poll_task(client, task_id)
            if task_result.get("status") == "failed":
                log_error(f"Task failed: {task_result.get('error')}")
                return 1

            # Give pipeline a moment to persist final state
            await asyncio.sleep(3)

        # Step 4: Verify results (outside httpx context to reuse connections)
        results = await step_verify_results(project_root)

        # Summary
        print("\n" + "=" * 70)
        print("Test Summary")
        print("=" * 70)

        pg_articles = results.get("pg_articles", 0)
        pg_vectors = results.get("pg_vectors", 0)
        neo4j_articles = results.get("neo4j_articles", 0)
        neo4j_entities = results.get("neo4j_entities", 0)

        if pg_articles > 0:
            log_info(f"✓ {pg_articles} article(s) stored in PostgreSQL")
        else:
            log_error("✗ No articles found in PostgreSQL")

        if pg_vectors > 0:
            log_info(f"✓ {pg_vectors} vector(s) stored in PostgreSQL")
        else:
            log_warn("⚠ No vectors found in PostgreSQL (may require LLM API)")

        if neo4j_articles > 0:
            log_info(f"✓ {neo4j_articles} Article node(s) in Neo4j")
        else:
            log_warn("⚠ No Article nodes in Neo4j (may require entity extraction)")

        print("=" * 70)

        # Overall result
        if pg_articles > 0:
            log_info("Pipeline test PASSED")
            return 0
        else:
            log_error("Pipeline test FAILED: No articles stored")
            return 1

    except httpx.ConnectError:
        log_error(f"Cannot connect to Weaver app at {app_url}")
        log_error("Is the app running? Use --no-start to skip starting the app")
        return 1
    except httpx.TimeoutException as e:
        log_error(f"Request timeout: {e}")
        return 1
    except Exception as e:
        log_error(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        return 1
    finally:
        if proc:
            stop_app_process(proc)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Full pipeline E2E test")
    parser.add_argument(
        "--app-url",
        default=os.getenv("WEAVER_APP_URL", DEFAULT_APP_URL),
        help=f"Weaver app base URL (default: {DEFAULT_APP_URL})",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=DEFAULT_MAX_ITEMS,
        help=f"Maximum items to process (default: {DEFAULT_MAX_ITEMS})",
    )
    parser.add_argument(
        "--no-start",
        action="store_true",
        help="Don't start the app; assume it's already running at --app-url",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("WEAVER_API_KEY", DEFAULT_API_KEY),
        help=f"API key (default: from env or {DEFAULT_API_KEY})",
    )
    args = parser.parse_args()

    # Update globals with parsed args
    global _headers
    if args.api_key != DEFAULT_API_KEY:
        _headers = {"X-API-Key": args.api_key, "Content-Type": "application/json"}

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    return asyncio.run(
        run_test(
            project_root=project_root,
            app_url=args.app_url,
            max_items=args.max_items,
            start_app=not args.no_start,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
