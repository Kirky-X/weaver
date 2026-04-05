#!/usr/bin/env python
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified API test script for Weaver.

Supports two subcommands:
  - e2e: End-to-end pipeline test via HTTP API
  - audit: Comprehensive API endpoint audit

Usage:
    # E2E test
    uv run scripts/test_api.py e2e --mode 36kr --max-items 5
    uv run scripts/test_api.py e2e --mode rss --no-start

    # API audit
    uv run scripts/test_api.py audit --port 8001
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_API_KEY = "dev-api-key-for-testing-purposes"
DEFAULT_APP_URL = "http://localhost:8000"
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


# ─────────────────────────────────────────────────────────────────────────────
# Color output
# ─────────────────────────────────────────────────────────────────────────────


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


# ─────────────────────────────────────────────────────────────────────────────
# App process management
# ─────────────────────────────────────────────────────────────────────────────


APP_ENV = {
    "WEAVER_POSTGRES__DSN": "postgresql+asyncpg://postgres:postgres@localhost:5432/weaver",
    "NEO4J_PASSWORD": "password",
    "POSTGRES_PASSWORD": os.getenv("POSTGRES_PASSWORD", "postgres"),
    "ENVIRONMENT": "development",
    "WEAVER_API__API_KEY": os.getenv(
        "WEAVER_API__API_KEY", "dev_api_key_1234567890123456789012345678"
    ),
}


def start_app_process(project_root: str, port: int = 8000) -> subprocess.Popen[bytes]:
    """Start Weaver app as a background subprocess."""
    log_info("Starting Weaver app...")

    env = dict(os.environ)
    env.update(APP_ENV)

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.main:app",
            "--host",
            "0.0.0.0",
            f"--port",
            str(port),
        ],
        cwd=project_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
    )

    app_url = f"http://localhost:{port}"
    for attempt in range(30):
        try:
            import httpx

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


# ─────────────────────────────────────────────────────────────────────────────
# HTTP API helpers
# ─────────────────────────────────────────────────────────────────────────────


def get_headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key, "Content-Type": "application/json"}


def api_get(
    client, path: str, api_key: str, timeout: float = API_TIMEOUT_SECONDS
) -> dict[str, Any]:
    """Send GET request and unwrap API envelope."""

    resp = client.get(path, headers=get_headers(api_key), timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f"API GET {path} failed: {resp.status_code} {resp.text}")
    body = resp.json()
    return body.get("data", body)


def api_post(
    client, path: str, data: dict[str, Any], api_key: str, timeout: float = API_TIMEOUT_SECONDS
):
    """Send POST request to API."""

    return client.post(path, headers=get_headers(api_key), json=data, timeout=timeout)


# ─────────────────────────────────────────────────────────────────────────────
# E2E Test Implementation
# ─────────────────────────────────────────────────────────────────────────────


async def register_source(client, source: dict[str, Any], api_key: str) -> bool:
    """Register a single source. Returns True if success or already exists."""

    source_id = source["id"]
    log_source(source_id, f"Registering source at {source['url']}...")

    resp = api_post(client, "/api/v1/sources", source, api_key)

    if resp.status_code == 201:
        log_source(source_id, "Source registered (201)")
        return True
    elif resp.status_code == 409:
        log_source(source_id, "Source already exists (409)")
        return True
    else:
        log_error(f"  [{source_id}] Failed: {resp.status_code} {resp.text}")
        return False


async def register_sources(client, sources: list[dict[str, Any]], api_key: str) -> bool:
    """Register all sources. Returns True if all succeeded."""
    log_step("1/4", "Registering sources...")
    results = await asyncio.gather(*(register_source(client, s, api_key) for s in sources))
    return all(results)


async def trigger_pipeline(client, source_id: str, max_items: int, api_key: str) -> str | None:
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
        api_key,
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
    client, sources: list[dict[str, Any]], max_items: int, api_key: str
) -> dict[str, str | None]:
    """Trigger pipelines for all sources."""
    log_step("2/4", f"Triggering pipelines (max_items={max_items})...")
    task_ids: dict[str, str | None] = {}
    for source in sources:
        task_ids[source["id"]] = await trigger_pipeline(client, source["id"], max_items, api_key)
    return task_ids


async def poll_task(client, source_id: str, task_id: str, api_key: str) -> dict[str, Any]:
    """Poll a single task until completed, failed, or timeout."""
    deadline = time.time() + POLL_TIMEOUT_SECONDS

    while time.time() < deadline:
        try:
            data = api_get(client, f"/api/v1/pipeline/tasks/{task_id}", api_key)
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
    return api_get(client, f"/api/v1/pipeline/tasks/{task_id}", api_key)


async def poll_tasks(
    client, task_ids: dict[str, str | None], api_key: str
) -> dict[str, dict[str, Any]]:
    """Poll all tasks."""
    log_step("3/4", "Polling task status...")
    results: dict[str, dict[str, Any]] = {}
    for source_id, task_id in task_ids.items():
        if not task_id:
            results[source_id] = {"status": "failed", "error": "No task_id"}
            continue
        results[source_id] = await poll_task(client, source_id, task_id, api_key)
    return results


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
        driver.close()
    except Exception as e:
        log_warn(f"  Neo4j verification failed: {e}")
        results["neo4j_error"] = str(e)

    return results


def resolve_sources(mode: str) -> list[dict[str, Any]]:
    """Return source list based on mode."""
    sources = []
    if mode in ("36kr", "all"):
        sources.append(SOURCE_36KR)
    if mode in ("rss", "all"):
        sources.extend(RSS_SOURCES)
    return sources


async def run_e2e_test(args: argparse.Namespace) -> int:
    """Run the E2E test."""
    import httpx

    sources = resolve_sources(args.mode)
    if not sources:
        log_error(f"Unknown mode: {args.mode}")
        return 1

    project_root = Path(__file__).parent.parent
    app_url = args.app_url or DEFAULT_APP_URL
    api_key = args.api_key or DEFAULT_API_KEY

    print("=" * 70)
    print(f"Weaver {args.mode.upper()} Pipeline E2E Test")
    print("=" * 70)
    print(f"  App URL:   {app_url}")
    print(f"  Mode:      {args.mode}")
    print(f"  Max items: {args.max_items}")
    print(f"  Start app: {not args.no_start}")
    print("=" * 70)

    proc: subprocess.Popen[bytes] | None = None

    try:
        if not args.no_start:
            proc = start_app_process(str(project_root), port=int(app_url.split(":")[-1]))

        await asyncio.sleep(3)

        with httpx.Client(base_url=app_url, timeout=API_TIMEOUT_SECONDS) as client:
            # Step 1: Register
            if not await register_sources(client, sources, api_key):
                return 1

            # Step 2: Trigger
            task_ids = await trigger_pipelines(client, sources, args.max_items, api_key)
            if not any(task_ids.values()):
                log_error("All pipeline triggers failed")
                return 1

            # Step 3: Poll
            task_results = await poll_tasks(client, task_ids, api_key)
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

        print("=" * 70)
        return 0 if total > 0 else 1

    except httpx.ConnectError:
        log_error(f"Cannot connect to Weaver app at {app_url}")
        log_error("Is the app running? Use --no-start to skip starting the app")
        return 1
    except Exception as e:
        log_error(f"Unexpected error: {e}")
        __import__("traceback").print_exc()
        return 1
    finally:
        if proc:
            stop_app_process(proc)


# ─────────────────────────────────────────────────────────────────────────────
# Audit Implementation
# ─────────────────────────────────────────────────────────────────────────────


async def run_audit_test(args: argparse.Namespace) -> int:
    """Run the API audit test."""
    import httpx

    app_url = f"http://localhost:{args.port}"
    api_key = args.api_key or DEFAULT_API_KEY
    log_file = Path(__file__).parent.parent / "http_audit.log"
    request_log_file = Path(__file__).parent.parent / "http_requests.jsonl"

    # Clear previous logs
    if log_file.exists():
        log_file.unlink()
    if request_log_file.exists():
        request_log_file.unlink()

    print("=" * 70)
    print("HTTP API Comprehensive Audit")
    print("=" * 70)
    print(f"API Base URL: {app_url}")
    print(f"API Key: {api_key[:15]}...")

    async def wait_for_server(client: httpx.AsyncClient, max_wait: int = 30) -> bool:
        for i in range(max_wait):
            try:
                resp = await client.get(f"{app_url}/health", timeout=2.0)
                if resp.status_code == 200:
                    print(f"Server ready after {i + 1}s")
                    return True
            except Exception:
                pass
            await asyncio.sleep(1)
        return False

    async def log_request_response(
        method: str, path: str, request_data: dict, response: httpx.Response
    ):
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "request": {
                "method": method,
                "path": path,
                "headers": request_data.get("headers", {}),
                "body": request_data.get("body"),
            },
            "response": {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body": response.text[:2000] if response.text else None,
            },
        }
        with open(request_log_file, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    async def test_endpoint(
        client: httpx.AsyncClient,
        method: str,
        path: str,
        body: dict | None,
        description: str = "",
    ) -> bool:
        url = f"{app_url}{path}"
        headers = get_headers(api_key)

        # Skip auth for health/metrics
        if path in ("/health", "/metrics"):
            headers = {}

        try:
            if method == "GET":
                resp = await client.get(url, headers=headers, timeout=15.0)
            elif method == "POST":
                resp = await client.post(url, headers=headers, json=body, timeout=15.0)
            elif method == "PUT":
                resp = await client.put(url, headers=headers, json=body, timeout=15.0)
            elif method == "DELETE":
                resp = await client.delete(url, headers=headers, timeout=15.0)
            elif method == "PATCH":
                resp = await client.patch(url, headers=headers, json=body, timeout=15.0)
            else:
                return False

            status_icon = "✓" if resp.status_code < 400 else "✗"
            desc_str = f" ({description})" if description else ""
            print(f"{status_icon} {method} {path} -> {resp.status_code}{desc_str}")

            await log_request_response(method, path, {"headers": headers, "body": body}, resp)
            return resp.status_code < 400

        except Exception as e:
            print(f"✗ {method} {path} -> ERROR: {e}")
            await log_request_response(
                method,
                path,
                {"headers": headers, "body": body},
                httpx.Response(status_code=0, headers={}, content=f"Error: {e}".encode()),
            )
            return False

    async with httpx.AsyncClient() as client:
        print("\nWaiting for server...")
        if not await wait_for_server(client):
            print("Server not ready. Start with:")
            print(f"  uv run uvicorn src.main:app --port {args.port}")
            return 1

        results = {"passed": 0, "failed": 0}

        print("\n" + "=" * 70)
        print("Testing API Endpoints")
        print("=" * 70)

        # System
        print("\n--- System ---")
        for path, desc in [("/health", "basic"), ("/metrics", "prometheus")]:
            if await test_endpoint(client, "GET", path, None, desc):
                results["passed"] += 1
            else:
                results["failed"] += 1

        # Sources API
        print("\n--- Sources API ---")
        endpoints = [
            ("GET", "/api/v1/sources", None, "list sources"),
            (
                "POST",
                "/api/v1/sources",
                {"id": "test_audit", "name": "Test", "url": "https://test.com/rss"},
                "create",
            ),
            ("DELETE", "/api/v1/sources/test_audit", None, "delete"),
        ]
        for method, path, body, desc in endpoints:
            if await test_endpoint(client, method, path, body, desc):
                results["passed"] += 1
            else:
                results["failed"] += 1

        # Articles API
        print("\n--- Articles API ---")
        endpoints = [
            ("GET", "/api/v1/articles", None, "list"),
            ("GET", "/api/v1/articles?page=1&page_size=5", None, "pagination"),
        ]
        for method, path, body, desc in endpoints:
            if await test_endpoint(client, method, path, body, desc):
                results["passed"] += 1
            else:
                results["failed"] += 1

        # Search API
        print("\n--- Search API ---")
        endpoints = [
            ("GET", "/api/v1/search?q=test&mode=local", None, "local search"),
            ("POST", "/api/v1/search/drift", {"query": "test"}, "DRIFT search"),
        ]
        for method, path, body, desc in endpoints:
            if await test_endpoint(client, method, path, body, desc):
                results["passed"] += 1
            else:
                results["failed"] += 1

        # Graph API
        print("\n--- Graph API ---")
        endpoints = [
            ("GET", "/api/v1/graph/metrics", None, "metrics"),
            ("GET", "/api/v1/graph/relation-types", None, "relation types"),
        ]
        for method, path, body, desc in endpoints:
            if await test_endpoint(client, method, path, body, desc):
                results["passed"] += 1
            else:
                results["failed"] += 1

    print("\n" + "=" * 70)
    print(f"Results: {results['passed']} passed, {results['failed']} failed")
    print("=" * 70)
    print(f"\nLogs saved to:")
    print(f"  - {log_file}")
    print(f"  - {request_log_file}")

    return 0 if results["failed"] == 0 else 1


# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unified API test script for Weaver",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # E2E subcommand
    p_e2e = sub.add_parser("e2e", help="End-to-end pipeline test")
    p_e2e.add_argument(
        "--mode",
        choices=["36kr", "rss", "all"],
        default="36kr",
        help="Test mode: 36kr (default), rss, or all",
    )
    p_e2e.add_argument(
        "--app-url",
        default=os.getenv("WEAVER_APP_URL", DEFAULT_APP_URL),
        help=f"Weaver app base URL (default: {DEFAULT_APP_URL})",
    )
    p_e2e.add_argument(
        "--max-items",
        type=int,
        default=5,
        help="Maximum items per source (default: 5)",
    )
    p_e2e.add_argument(
        "--no-start",
        action="store_true",
        help="Don't start the app; assume it's already running",
    )
    p_e2e.add_argument(
        "--api-key",
        default=os.getenv("WEAVER_API_KEY", DEFAULT_API_KEY),
        help="API key (default: from env or built-in)",
    )

    # Audit subcommand
    p_audit = sub.add_parser("audit", help="API endpoint audit")
    p_audit.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Server port (default: 8000)",
    )
    p_audit.add_argument(
        "--api-key",
        default=os.getenv("WEAVER_API_KEY", DEFAULT_API_KEY),
        help="API key (default: from env or built-in)",
    )

    args = parser.parse_args()

    if args.command == "e2e":
        return asyncio.run(run_e2e_test(args))
    elif args.command == "audit":
        return asyncio.run(run_audit_test(args))
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
