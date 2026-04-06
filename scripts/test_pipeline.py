#!/usr/bin/env python
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified pipeline test script via HTTP API.

Supports multiple test modes:
  - newsnow: Test NewsNow data ingestion
  - rss: Test RSS feed ingestion
  - strategy: Test database failover strategy

All interactions are performed through HTTP API endpoints.
No backward compatibility with old scripts.

Usage:
    # NewsNow mode (default)
    uv run scripts/test_pipeline.py --mode newsnow --max-items 5

    # NewsNow with custom source
    uv run scripts/test_pipeline.py --mode newsnow --source-id hupu --max-items 5

    # RSS mode
    uv run scripts/test_pipeline.py --mode rss --source solidot --max-items 2

    # Strategy mode (test database failover)
    uv run scripts/test_pipeline.py --mode strategy

    # With database cleanup
    uv run scripts/test_pipeline.py --clear-db --max-items 3
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ─────────────────────────────────────────────────────────────────────────────
# Phase indicators
# ─────────────────────────────────────────────────────────────────────────────

PASS = "\u2713"
FAIL = "\u2717"


def phase_header(name: str) -> None:
    width = 60
    print(f"\n{'=' * width}")
    print(f"  {name}")
    print(f"{'=' * width}")


def step(label: str, ok: bool, detail: str = "") -> None:
    mark = PASS if ok else FAIL
    suffix = f"  ({detail})" if detail else ""
    print(f"  {mark} {label}{suffix}")


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TaskStatus:
    """Pipeline task status."""

    task_id: str
    status: str
    source_id: str | None = None
    queued_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    total_processed: int = 0
    completed_count: int = 0
    failed_count: int = 0
    error: str | None = None


@dataclass
class TestResult:
    """Test result summary."""

    success: bool
    message: str
    articles_count: int = 0
    elapsed_seconds: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# API Client
# ─────────────────────────────────────────────────────────────────────────────


class PipelineAPIClient:
    """HTTP API client for pipeline operations."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        """Get API headers."""
        return {"X-API-Key": self.api_key}

    async def create_source(self, config: dict[str, Any]) -> dict[str, Any]:
        """Create a data source via API.

        Args:
            config: Source configuration.

        Returns:
            Created source data.

        Raises:
            httpx.HTTPStatusError: If request fails.
        """
        url = f"{self.base_url}/api/v1/sources"
        response = await self._client.post(url, json=config, headers=self._headers())

        if response.status_code == 201:
            return response.json()["data"]
        elif response.status_code == 409:
            # Source already exists, get it
            source_id = config["id"]
            return await self.get_source(source_id)
        else:
            response.raise_for_status()
            return {}

    async def get_source(self, source_id: str) -> dict[str, Any]:
        """Get a source by ID.

        Args:
            source_id: Source identifier.

        Returns:
            Source data.
        """
        url = f"{self.base_url}/api/v1/sources/{source_id}"
        response = await self._client.get(url, headers=self._headers())
        response.raise_for_status()
        return response.json()["data"]

    async def trigger_pipeline(
        self,
        source_id: str,
        max_items: int | None = None,
    ) -> str:
        """Trigger pipeline for a source.

        Args:
            source_id: Source identifier.
            max_items: Maximum items to process.

        Returns:
            Task ID.
        """
        url = f"{self.base_url}/api/v1/pipeline/trigger"
        payload: dict[str, Any] = {
            "source_id": source_id,
            "force": True,
        }
        if max_items is not None:
            payload["max_items"] = max_items

        response = await self._client.post(url, json=payload, headers=self._headers())
        response.raise_for_status()
        return response.json()["data"]["task_id"]

    async def get_task_status(self, task_id: str) -> TaskStatus:
        """Get pipeline task status.

        Args:
            task_id: Task identifier.

        Returns:
            Task status.
        """
        url = f"{self.base_url}/api/v1/pipeline/tasks/{task_id}"
        response = await self._client.get(url, headers=self._headers())
        response.raise_for_status()
        data = response.json()["data"]
        return TaskStatus(
            task_id=data.get("task_id", task_id),
            status=data.get("status", "unknown"),
            source_id=data.get("source_id"),
            queued_at=data.get("queued_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            total_processed=data.get("total_processed", 0),
            completed_count=data.get("completed_count", 0),
            failed_count=data.get("failed_count", 0),
            error=data.get("error"),
        )

    async def wait_for_task(
        self,
        task_id: str,
        timeout: float = 300.0,
        poll_interval: float = 5.0,
    ) -> TaskStatus:
        """Wait for task completion.

        Args:
            task_id: Task identifier.
            timeout: Maximum wait time in seconds.
            poll_interval: Polling interval in seconds.

        Returns:
            Final task status.

        Raises:
            TimeoutError: If task doesn't complete in time.
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            status = await self.get_task_status(task_id)

            if status.status in ("completed", "failed"):
                return status

            print(
                f"    Task {task_id[:8]}... status: {status.status}, "
                f"processed: {status.total_processed}, "
                f"completed: {status.completed_count}, failed: {status.failed_count}"
            )

            await asyncio.sleep(poll_interval)

        raise TimeoutError(f"Task {task_id} did not complete within {timeout} seconds")

    async def list_articles(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """List articles.

        Args:
            page: Page number.
            page_size: Items per page.

        Returns:
            Articles list with total count.
        """
        url = f"{self.base_url}/api/v1/articles"
        params = {"page": page, "page_size": page_size}
        response = await self._client.get(url, params=params, headers=self._headers())
        response.raise_for_status()
        return response.json()["data"]


# ─────────────────────────────────────────────────────────────────────────────
# Source Configurations
# ─────────────────────────────────────────────────────────────────────────────


RSS_SOURCES: dict[str, dict[str, Any]] = {
    "solidot": {
        "url": "https://www.solidot.org/index.rss",
        "name": "Solidot",
        "credibility": 0.70,
    },
    "cnbeta": {
        "url": "https://plink.anyfeeder.com/cnbeta",
        "name": "CNBeta",
        "credibility": 0.70,
    },
    "huxiu": {
        "url": "https://plink.anyfeeder.com/huxiu",
        "name": "Huxiu",
        "credibility": 0.70,
    },
}


def build_newsnow_source_config(source_id: str) -> dict[str, Any]:
    """Build NewsNow source configuration."""
    return {
        "id": f"newsnow-{source_id}",
        "name": f"NewsNow {source_id}",
        "url": f"https://www.newsnow.world/api/s?id={source_id}",
        "source_type": "newsnow",
        "enabled": True,
        "interval_minutes": 30,
    }


def build_rss_source_config(source: str) -> dict[str, Any]:
    """Build RSS source configuration."""
    if source not in RSS_SOURCES:
        raise ValueError(f"Unknown RSS source: {source}. Available: {list(RSS_SOURCES.keys())}")

    src = RSS_SOURCES[source]
    return {
        "id": f"rss-{source}",
        "name": src["name"],
        "url": src["url"],
        "source_type": "rss",
        "enabled": True,
        "interval_minutes": 30,
        "credibility": src["credibility"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Server Management
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ServerContext:
    """Server context for testing."""

    container: Any
    strategy: Any
    relational_type: str
    graph_type: str


async def start_server(port: int = 8000, container: Any = None) -> tuple[Any, asyncio.Task]:
    """Start the FastAPI server.

    Args:
        port: Server port.
        container: Container instance.

    Returns:
        Tuple of (server, task).
    """
    import uvicorn

    from main import create_app

    app = create_app(container)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())

    # Wait for server to start
    await asyncio.sleep(3)

    return server, task


async def setup_strategy_mode() -> ServerContext:
    """Setup strategy mode with fallback databases.

    Returns:
        Server context with strategy info.
    """
    import container as container_module
    from config.settings import Settings
    from container import Container

    # Force fallback databases by setting invalid hosts
    os.environ["POSTGRES_HOST"] = "nonexistent.invalid"
    os.environ["NEO4J_URI"] = "bolt://nonexistent.invalid:7687"
    os.environ["REDIS_HOST"] = "nonexistent.invalid"

    print("  Forcing fallback databases (DuckDB + LadybugDB + CashewsRedis)")

    settings = Settings()
    container = Container().configure(settings)
    await container.startup()
    container_module._container = container

    strategy = container._strategy
    relational_type = strategy.relational_type
    graph_type = strategy.graph_type

    return ServerContext(
        container=container,
        strategy=strategy,
        relational_type=relational_type,
        graph_type=graph_type,
    )


async def setup_normal_mode() -> ServerContext:
    """Setup normal mode with fallback databases.

    Returns:
        Server context with strategy info.
    """
    import container as container_module
    from config.settings import Settings
    from container import Container

    # Use fallback databases for testing
    os.environ.setdefault("POSTGRES_ENABLED", "false")
    os.environ.setdefault("NEO4J_ENABLED", "false")
    os.environ.setdefault("DUCKDB_ENABLED", "true")
    os.environ.setdefault("LADYBUG_ENABLED", "true")

    settings = Settings()
    container = Container().configure(settings)
    await container.startup()
    container_module._container = container

    strategy = container._strategy
    return ServerContext(
        container=container,
        strategy=strategy,
        relational_type=strategy.relational_type,
        graph_type=strategy.graph_type,
    )


async def shutdown_server(server: Any, container: Any) -> None:
    """Shutdown server and container.

    Args:
        server: Uvicorn server instance.
        container: Container instance.
    """
    server.should_exit = True
    await asyncio.sleep(1)
    await container.shutdown()


# ─────────────────────────────────────────────────────────────────────────────
# Database Cleanup
# ─────────────────────────────────────────────────────────────────────────────


async def clear_databases(server_ctx: ServerContext) -> None:
    """Clear all data from test databases.

    Note: This operation bypasses API, as there's no cleanup endpoint.

    Args:
        server_ctx: Server context with database pools.
    """
    import sqlalchemy

    phase_header("PHASE: Clear Databases")

    pool = server_ctx.strategy.relational_pool
    graph_pool = server_ctx.strategy.graph_pool

    # Clear DuckDB/PostgreSQL tables
    tables = [
        "articles",
        "article_vectors",
        "entity_vectors",
        "source_authorities",
        "llm_failures",
        "llm_usage_raw",
        "llm_usage_hourly",
        "pending_sync",
        "unknown_relation_types",
    ]

    async with pool.session_context() as session:
        for table in tables:
            with contextlib.suppress(Exception):
                await session.execute(sqlalchemy.text(f"DELETE FROM {table}"))
        await session.commit()
    step("Relational tables cleared", True)

    # Clear LadybugDB/Neo4j nodes
    if graph_pool:
        with contextlib.suppress(Exception):
            await graph_pool.execute_query("MATCH ()-[r]->() DELETE r")
            await graph_pool.execute_query("MATCH (n) DELETE n")
        step("Graph nodes cleared", True)


# ─────────────────────────────────────────────────────────────────────────────
# Test Runners
# ─────────────────────────────────────────────────────────────────────────────


async def run_newsnow_test(
    client: PipelineAPIClient,
    source_id: str,
    max_items: int,
    timeout: int,
) -> TestResult:
    """Run NewsNow mode test.

    Args:
        client: API client.
        source_id: NewsNow source ID.
        max_items: Maximum items to process.
        timeout: Pipeline timeout.

    Returns:
        Test result.
    """
    phase_header("PHASE 1: Source Creation")
    source_config = build_newsnow_source_config(source_id)
    source = await client.create_source(source_config)
    step(f"Created source: {source['id']}", True)

    phase_header("PHASE 2: Pipeline Execution")
    task_id = await client.trigger_pipeline(source["id"], max_items)
    step(f"Pipeline triggered", True, f"task_id: {task_id[:8]}...")

    status = await client.wait_for_task(task_id, timeout=timeout)
    step(
        f"Task completed",
        status.status == "completed",
        f"status: {status.status}",
    )

    if status.error:
        step(f"Task error", False, status.error)

    phase_header("PHASE 3: Verification")
    articles = await client.list_articles(page=1, page_size=1)
    total = articles.get("total", 0)
    step(f"Articles stored", total > 0, f"{total} articles")

    return TestResult(
        success=status.status == "completed" and total > 0,
        message=f"NewsNow test: {status.status}",
        articles_count=total,
        details={"task_id": task_id, "source_id": source["id"]},
    )


async def run_rss_test(
    client: PipelineAPIClient,
    source: str,
    max_items: int,
    timeout: int,
) -> TestResult:
    """Run RSS mode test.

    Args:
        client: API client.
        source: RSS source name.
        max_items: Maximum items to process.
        timeout: Pipeline timeout.

    Returns:
        Test result.
    """
    phase_header("PHASE 1: Source Creation")
    source_config = build_rss_source_config(source)
    created = await client.create_source(source_config)
    step(f"Created source: {created['id']}", True)

    phase_header("PHASE 2: Pipeline Execution")
    task_id = await client.trigger_pipeline(created["id"], max_items)
    step(f"Pipeline triggered", True, f"task_id: {task_id[:8]}...")

    status = await client.wait_for_task(task_id, timeout=timeout)
    step(
        f"Task completed",
        status.status == "completed",
        f"status: {status.status}",
    )

    if status.error:
        step(f"Task error", False, status.error)

    phase_header("PHASE 3: Verification")
    articles = await client.list_articles(page=1, page_size=1)
    total = articles.get("total", 0)
    step(f"Articles stored", total > 0, f"{total} articles")

    return TestResult(
        success=status.status == "completed" and total > 0,
        message=f"RSS test: {status.status}",
        articles_count=total,
        details={"task_id": task_id, "source_id": created["id"]},
    )


async def run_strategy_test(
    client: PipelineAPIClient,
    source_id: str,
    max_items: int,
    timeout: int,
    server_ctx: ServerContext,
) -> TestResult:
    """Run Strategy mode test.

    Args:
        client: API client.
        source_id: NewsNow source ID.
        max_items: Maximum items to process.
        timeout: Pipeline timeout.
        server_ctx: Server context with strategy info.

    Returns:
        Test result.
    """
    # Verify fallback databases
    phase_header("PHASE 1: Strategy Verification")
    step(
        f"Relational database",
        server_ctx.relational_type == "duckdb",
        server_ctx.relational_type,
    )
    step(
        f"Graph database",
        server_ctx.graph_type == "ladybug",
        server_ctx.graph_type,
    )

    if server_ctx.relational_type != "duckdb" or server_ctx.graph_type != "ladybug":
        return TestResult(
            success=False,
            message="Strategy mode failed: fallback databases not used",
            details={
                "relational_type": server_ctx.relational_type,
                "graph_type": server_ctx.graph_type,
            },
        )

    # Run pipeline test
    phase_header("PHASE 2: Source Creation")
    source_config = build_newsnow_source_config(source_id)
    source = await client.create_source(source_config)
    step(f"Created source: {source['id']}", True)

    phase_header("PHASE 3: Pipeline Execution")
    task_id = await client.trigger_pipeline(source["id"], max_items)
    step(f"Pipeline triggered", True, f"task_id: {task_id[:8]}...")

    status = await client.wait_for_task(task_id, timeout=timeout)
    step(
        f"Task completed",
        status.status == "completed",
        f"status: {status.status}",
    )

    phase_header("PHASE 4: Verification")
    articles = await client.list_articles(page=1, page_size=1)
    total = articles.get("total", 0)
    step(f"Articles stored", total > 0, f"{total} articles")

    return TestResult(
        success=status.status == "completed" and total > 0,
        message=f"Strategy test: {status.status}",
        articles_count=total,
        details={
            "relational_type": server_ctx.relational_type,
            "graph_type": server_ctx.graph_type,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────


async def main(args: argparse.Namespace) -> int:
    """Main entry point."""
    print("=" * 60)
    print(f"  Pipeline Test: {args.mode.upper()} mode")
    print("=" * 60)

    start_time = time.time()

    # Setup server
    phase_header("PHASE 0: Infrastructure Initialization")

    if args.mode == "strategy":
        server_ctx = await setup_strategy_mode()
    else:
        server_ctx = await setup_normal_mode()

    step(
        f"Database: {server_ctx.relational_type} + {server_ctx.graph_type}",
        True,
    )

    # Clear databases if requested
    if args.clear_db:
        await clear_databases(server_ctx)

    # Start API server
    server, _server_task = await start_server(args.port, server_ctx.container)
    step(f"API server started", True, f"port: {args.port}")

    try:
        # Get API key
        from config.settings import Settings

        settings = Settings()
        api_key = settings.api.get_api_key()
        base_url = f"http://127.0.0.1:{args.port}"

        # Create API client
        client = PipelineAPIClient(base_url, api_key, timeout=args.timeout)

        # Run test based on mode
        if args.mode == "newsnow":
            result = await run_newsnow_test(client, args.source_id, args.max_items, args.timeout)
        elif args.mode == "rss":
            result = await run_rss_test(client, args.source, args.max_items, args.timeout)
        elif args.mode == "strategy":
            result = await run_strategy_test(
                client, args.source_id, args.max_items, args.timeout, server_ctx
            )
        else:
            print(f"Unknown mode: {args.mode}")
            return 1

        await client.close()

        # Summary
        elapsed = time.time() - start_time
        phase_header("SUMMARY")
        print(f"  Elapsed: {elapsed:.1f}s")
        print(f"  Articles: {result.articles_count}")
        print(f"  Database: {server_ctx.relational_type} + {server_ctx.graph_type}")

        if result.success:
            print(f"\n  Pipeline test PASSED")
            return 0
        else:
            print(f"\n  Pipeline test FAILED — {result.message}")
            return 1

    except Exception as e:
        print(f"\n  ERROR: {e}")
        __import__("traceback").print_exc()
        return 1

    finally:
        print("\nShutting down...")
        await shutdown_server(server, server_ctx.container)
        print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Unified pipeline test script via HTTP API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # NewsNow mode (default)
    uv run scripts/test_pipeline.py --mode newsnow --max-items 5

    # NewsNow with custom source
    uv run scripts/test_pipeline.py --mode newsnow --source-id hupu --max-items 5

    # RSS mode
    uv run scripts/test_pipeline.py --mode rss --source solidot --max-items 2

    # Strategy mode (test database failover)
    uv run scripts/test_pipeline.py --mode strategy

    # With database cleanup
    uv run scripts/test_pipeline.py --clear-db --max-items 3
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["newsnow", "rss", "strategy"],
        default="newsnow",
        help="Test mode (default: newsnow)",
    )
    parser.add_argument(
        "--source",
        default="solidot",
        help="RSS source name for rss mode (default: solidot)",
    )
    parser.add_argument(
        "--source-id",
        default="36kr",
        help="NewsNow source ID for newsnow mode (default: 36kr)",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=5,
        help="Maximum items to process (default: 5)",
    )
    parser.add_argument(
        "--clear-db",
        action="store_true",
        help="Clear databases before testing",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Pipeline timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="API server port (default: 8000)",
    )

    args = parser.parse_args()
    exit_code = asyncio.run(main(args))
    sys.exit(exit_code)
