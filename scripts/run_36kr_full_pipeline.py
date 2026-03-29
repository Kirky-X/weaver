#!/usr/bin/env python
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pipeline end-to-end test via HTTP API.

Supports testing different source types through --mode:
  36kr  : 36kr NewsNow source (default)
  rss   : RSS sources (cnbeta, huxiu)
  all   : Run both 36kr and RSS tests

Usage:
    uv run python scripts/run_36kr_full_pipeline.py [--mode 36kr|rss|all] [--max-items 5]
    uv run python scripts/run_36kr_full_pipeline.py --no-start --max-items 5
"""

from __future__ import annotations

import argparse
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
POLL_TIMEOUT_SECONDS = 180
API_TIMEOUT_SECONDS = 120

# Source definitions
SOURCE_36KR = {
    "id": "36kr",
    "name": "36kr",
    "url": "https://www.newsnow.world/api/s?id=36kr",
    "source_type": "newsnow",
    "enabled": True,
    "interval_minutes": 30,
}

RSS_SOURCES = [
    {
        "id": "cnbeta",
        "name": "CNBeta",
        "url": "https://plink.anyfeeder.com/cnbeta",
        "source_type": "rss",
        "enabled": True,
        "interval_minutes": 30,
        "tier": 2,
        "credibility": 0.7,
    },
    {
        "id": "huxiu",
        "name": "Huxiu",
        "url": "https://plink.anyfeeder.com/huxiu",
        "source_type": "rss",
        "enabled": True,
        "interval_minutes": 30,
        "tier": 2,
        "credibility": 0.7,
    },
]


# ─── Color output ─────────────────────────────────────────────────────────────


class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    NC = "\033[0m"


def log_info(msg: str) -> None:
    print(f"{Colors.GREEN}[INFO]{Colors.NC} {msg}")


def log_warn(msg: str) -> None:
    print(f"{Colors.YELLOW}[WARN]{Colors.NC} {msg}")


def log_error(msg: str) -> None:
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}")


def log_step(step: str, msg: str) -> None:
    print(f"{Colors.BLUE}[{step}]{Colors.NC} {msg}")


def log_source(source_id: str, msg: str) -> None:
    print(f"{Colors.CYAN}[{source_id}]{Colors.NC} {msg}")


# ─── App process management ───────────────────────────────────────────────────

APP_ENV = {
    "WEAVER_POSTGRES__DSN": "postgresql+asyncpg://postgres:postgres@localhost:5432/weaver",
    "NEO4J_PASSWORD": "password",
    "POSTGRES_PASSWORD": os.getenv("POSTGRES_PASSWORD", "postgres"),
    "ENVIRONMENT": "development",
    "WEAVER_API__API_KEY": os.getenv(
        "WEAVER_API__API_KEY", "dev_api_key_1234567890123456789012345678"
    ),
}


def start_app_process(project_root: str) -> subprocess.Popen[bytes]:
    """Start Weaver app as a background subprocess."""
    log_info("Starting Weaver app...")

    env = dict(os.environ)
    env.update(APP_ENV)

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd=project_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
    )

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
    """Send GET request and unwrap API envelope."""
    resp = client.get(path, headers=_headers, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f"API GET {path} failed: {resp.status_code} {resp.text}")
    body = resp.json()
    return body.get("data", body)


def api_post(
    client: httpx.Client, path: str, data: dict[str, Any], timeout: float = API_TIMEOUT_SECONDS
) -> httpx.Response:
    """Send POST request to API."""
    return client.post(path, headers=_headers, json=data, timeout=timeout)


# ─── Source registration ──────────────────────────────────────────────────────


async def register_source(client: httpx.Client, source: dict[str, Any]) -> bool:
    """Register a single source. Returns True if success or already exists."""
    source_id = source["id"]
    log_source(source_id, f"Registering source at {source['url']}...")

    resp = api_post(client, "/api/v1/sources", source)

    if resp.status_code == 201:
        log_source(source_id, "Source registered (201)")
        return True
    elif resp.status_code == 409:
        log_source(source_id, "Source already exists (409)")
        return True
    else:
        log_error(f"  [{source_id}] Failed: {resp.status_code} {resp.text}")
        return False


async def register_sources(client: httpx.Client, sources: list[dict[str, Any]]) -> bool:
    """Register all sources. Returns True if all succeeded."""
    log_step("1/4", "Registering sources...")
    results = await asyncio.gather(*(register_source(client, s) for s in sources))
    return all(results)


# ─── Pipeline triggering ──────────────────────────────────────────────────────


async def trigger_pipeline(client: httpx.Client, source_id: str, max_items: int) -> str | None:
    """Trigger pipeline for a source and return task_id."""
    log_source(source_id, "Triggering pipeline...")

    resp = api_post(
        client,
        "/api/v1/pipeline/trigger",
        {
            "source_id": source_id,
            "max_items": max_items,
            "force": True,
        },
    )

    if resp.status_code != 200:
        log_error(f"  [{source_id}] Trigger failed: {resp.status_code} {resp.text}")
        return None

    data = resp.json()
    data = data.get("data", data)
    task_id = data.get("task_id")
    log_source(source_id, f"Pipeline triggered, task_id={task_id}")
    return task_id


async def trigger_pipelines(
    client: httpx.Client, sources: list[dict[str, Any]], max_items: int
) -> dict[str, str | None]:
    """Trigger pipelines for all sources."""
    log_step("2/4", f"Triggering pipelines (max_items={max_items})...")
    task_ids: dict[str, str | None] = {}
    for source in sources:
        task_ids[source["id"]] = await trigger_pipeline(client, source["id"], max_items)
    return task_ids


# ─── Task polling ──────────────────────────────────────────────────────────────


async def poll_task(client: httpx.Client, source_id: str, task_id: str) -> dict[str, Any]:
    """Poll a single task until completed, failed, or timeout."""
    deadline = time.time() + POLL_TIMEOUT_SECONDS

    while time.time() < deadline:
        try:
            data = api_get(client, f"/api/v1/pipeline/tasks/{task_id}")
        except Exception as e:
            log_warn(f"  [{source_id}] Poll error: {e}")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue

        status = data.get("status", "unknown")
        completed = data.get("completed_count", 0)
        processing = data.get("processing_count", 0)
        failed = data.get("failed_count", 0)
        pending = data.get("pending_count", 0)

        print(
            f"  [{source_id}] status={status} | "
            f"completed={completed} processing={processing} failed={failed} pending={pending}"
        )

        if status in ("completed", "failed"):
            log_source(source_id, f"Task finished: {status}")
            return data

        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    log_error(f"  [{source_id}] Polling timeout after {POLL_TIMEOUT_SECONDS}s")
    return api_get(client, f"/api/v1/pipeline/tasks/{task_id}")


async def poll_tasks(
    client: httpx.Client, task_ids: dict[str, str | None]
) -> dict[str, dict[str, Any]]:
    """Poll all tasks."""
    log_step("3/4", "Polling task status...")
    results: dict[str, dict[str, Any]] = {}
    for source_id, task_id in task_ids.items():
        if not task_id:
            results[source_id] = {"status": "failed", "error": "No task_id"}
            continue
        results[source_id] = await poll_task(client, source_id, task_id)
    return results


# ─── Results verification ─────────────────────────────────────────────────────


async def verify_results(source_ids: list[str]) -> dict[str, Any]:
    """Query PostgreSQL and Neo4j to verify data was stored."""
    log_step("4/4", "Verifying database results...")
    results: dict[str, Any] = {}

    # PostgreSQL
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
            for sid in source_ids:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM articles WHERE source_url LIKE '%' || $1 || '%' OR source_host LIKE '%' || $1 || '%'",
                    sid,
                )
                results[f"pg_articles_{sid}"] = count
                log_info(f"  PostgreSQL articles for {sid}: {count}")

            total = await conn.fetchval("SELECT COUNT(*) FROM articles")
            results["pg_articles_total"] = total
            log_info(f"  PostgreSQL total articles: {total}")

            vectors = await conn.fetchval(
                "SELECT COUNT(*) FROM article_vectors WHERE embedding IS NOT NULL"
            )
            results["pg_vectors"] = vectors
            log_info(f"  PostgreSQL article_vectors: {vectors}")

            rows = await conn.fetch(
                "SELECT id, title, source_host, persist_status FROM articles ORDER BY created_at DESC LIMIT 10"
            )
            if rows:
                log_info("  Recent articles:")
                for row in rows:
                    title = (row["title"] or "")[:50]
                    host = row["source_host"] or "unknown"
                    print(f"    [{row['persist_status']}] ({host}) {title}...")
        finally:
            await conn.close()
    except Exception as e:
        log_warn(f"  PostgreSQL verification failed: {e}")
        results["pg_error"] = str(e)

    # Neo4j
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
        with driver.session() as session:
            articles = session.run("MATCH (a:Article) RETURN count(a) AS cnt").single()[0]
            results["neo4j_articles"] = articles
            log_info(f"  Neo4j Article nodes: {articles}")

            entities = session.run("MATCH (e:Entity) RETURN count(e) AS cnt").single()[0]
            results["neo4j_entities"] = entities
            log_info(f"  Neo4j Entity nodes: {entities}")

            rels = session.run("MATCH ()-[r]-() RETURN count(DISTINCT r) AS cnt").single()[0]
            results["neo4j_relationships"] = rels
            log_info(f"  Neo4j relationships: {rels}")
        driver.close()
    except Exception as e:
        log_warn(f"  Neo4j verification failed: {e}")
        results["neo4j_error"] = str(e)

    return results


# ─── Test runner ──────────────────────────────────────────────────────────────


def _resolve_sources(mode: str) -> list[dict[str, Any]]:
    """Return source list based on mode."""
    sources = []
    if mode in ("36kr", "all"):
        sources.append(SOURCE_36KR)
    if mode in ("rss", "all"):
        sources.extend(RSS_SOURCES)
    return sources


async def run_test(
    project_root: str,
    app_url: str,
    max_items: int,
    start_app: bool,
    mode: str,
) -> int:
    """Run the pipeline test. Returns 0 on success, 1 on failure."""
    sources = _resolve_sources(mode)
    if not sources:
        log_error(f"Unknown mode: {mode}")
        return 1

    mode_label = mode.upper() if mode != "all" else "ALL"
    print("=" * 70)
    print(f"Weaver {mode_label} Pipeline E2E Test")
    print("=" * 70)
    print(f"  App URL:   {app_url}")
    print(f"  Mode:      {mode}")
    print(f"  Max items: {max_items}")
    print(f"  Start app: {start_app}")
    print("  Sources:")
    for s in sources:
        print(f"    - {s['id']}: {s['url']}")
    print("=" * 70)

    proc: subprocess.Popen[bytes] | None = None

    try:
        if start_app:
            proc = start_app_process(project_root)

        await asyncio.sleep(3)

        with httpx.Client(base_url=app_url, timeout=API_TIMEOUT_SECONDS) as client:
            # Step 1: Register
            if not await register_sources(client, sources):
                return 1

            # Step 2: Trigger
            task_ids = await trigger_pipelines(client, sources, max_items)
            if not any(task_ids.values()):
                log_error("All pipeline triggers failed")
                return 1

            # Step 3: Poll
            task_results = await poll_tasks(client, task_ids)
            failed = [s for s, r in task_results.items() if r.get("status") == "failed"]
            if failed:
                log_warn(f"Some tasks failed: {failed}")

            await asyncio.sleep(3)

        # Step 4: Verify
        source_ids = [s["id"] for s in sources]
        results = await verify_results(source_ids)

        # Summary
        print("\n" + "=" * 70)
        print("Test Summary")
        print("=" * 70)

        total = results.get("pg_articles_total", 0)
        for s in sources:
            count = results.get(f"pg_articles_{s['id']}", 0)
            if count > 0:
                log_info(f"[{s['id']}] {count} article(s) in PostgreSQL")
            else:
                log_warn(f"[{s['id']}] No articles in PostgreSQL")

        if total > 0:
            log_info(f"Total {total} article(s) in PostgreSQL")
        else:
            log_error("No articles found in PostgreSQL")

        if results.get("pg_vectors", 0) > 0:
            log_info(f"{results['pg_vectors']} vector(s) in PostgreSQL")
        else:
            log_warn("No vectors found (may require LLM API)")

        if results.get("neo4j_articles", 0) > 0:
            log_info(f"{results['neo4j_articles']} Article node(s) in Neo4j")
        else:
            log_warn("No Article nodes in Neo4j")

        if results.get("neo4j_entities", 0) > 0:
            log_info(f"{results['neo4j_entities']} Entity nodes in Neo4j")

        print("=" * 70)

        return 0 if total > 0 else 1

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


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Weaver Pipeline E2E Test")
    parser.add_argument(
        "--mode",
        choices=["36kr", "rss", "all"],
        default="36kr",
        help="Test mode: 36kr (default), rss, or all",
    )
    parser.add_argument(
        "--app-url",
        default=os.getenv("WEAVER_APP_URL", DEFAULT_APP_URL),
        help=f"Weaver app base URL (default: {DEFAULT_APP_URL})",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=DEFAULT_MAX_ITEMS,
        help=f"Maximum items per source (default: {DEFAULT_MAX_ITEMS})",
    )
    parser.add_argument(
        "--no-start",
        action="store_true",
        help="Don't start the app; assume it's already running",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("WEAVER_API_KEY", DEFAULT_API_KEY),
        help="API key (default: from env or built-in)",
    )
    args = parser.parse_args()

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
            mode=args.mode,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
