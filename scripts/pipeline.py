#!/usr/bin/env python
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified pipeline management script.

Combines pipeline testing, pending article processing, and incomplete article reprocessing.

Usage:
    # Test modes
    uv run scripts/pipeline.py test --mode newsnow --max-items 5
    uv run scripts/pipeline.py test --mode rss --source solidot --max-items 2
    uv run scripts/pipeline.py test --mode strategy
    uv run scripts/pipeline.py test --mode all --clear-db

    # Processing modes (affects depth of pipeline)
    uv run scripts/pipeline.py test --processing-mode fast    # Phase 1 only (1-2min)
    uv run scripts/pipeline.py test --processing-mode deep    # Full pipeline (5-10min)

    # Process pending articles
    uv run scripts/pipeline.py process-pending

    # Reprocess incomplete articles
    uv run scripts/pipeline.py reprocess --incomplete
    uv run scripts/pipeline.py reprocess --article-id <uuid>

Processing Modes:
    fast: Phase 1 only (classifier → cleaner → categorizer → vectorize)
          - Fast ingestion without deep analysis
          - Skips entity extraction, quality scoring, credibility checks
          - Suitable for quick data collection

    deep: Full 4-phase processing
          - Phase 1: Classification, cleaning, categorization, vectorization
          - Phase 2: Batch merging
          - Phase 3: Entity extraction, analysis, quality, credibility
          - Phase 4: Persistence to graph database
          - Suitable for complete knowledge graph building

Note: To limit physical memory to 24GB, run with:
    systemd-run --scope -p MemoryMax=24G uv run scripts/pipeline.py ...
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import enum
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ─────────────────────────────────────────────────────────────────────────────
# Processing Mode Enum
# ─────────────────────────────────────────────────────────────────────────────


class ProcessingMode(str, enum.Enum):
    """Pipeline processing mode.

    FAST: Phase 1 only (classifier, cleaner, categorizer, vectorize)
          - 1-2 minutes per batch
          - No entity extraction, no quality scoring
          - Suitable for quick ingestion

    DEEP: Full 4-phase processing
          - 5-10 minutes per batch
          - Includes Phase 3 deep analysis (entities, quality, credibility)
          - Suitable for complete analysis
    """

    FAST = "fast"
    DEEP = "deep"


def get_mode_config(mode: ProcessingMode) -> dict[str, Any]:
    """Get mode-specific configuration overrides.

    Args:
        mode: Processing mode.

    Returns:
        Dictionary of configuration overrides for the mode.
    """
    if mode == ProcessingMode.FAST:
        return {
            "skip_entities": True,
            "skip_quality": True,
            "skip_credibility": True,
            "skip_batch_merger": True,
            "skip_phase3": True,
        }
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Server startup/shutdown constants
# ─────────────────────────────────────────────────────────────────────────────

# Server startup polling defaults
SERVER_STARTUP_TIMEOUT = 5.0  # HTTP client timeout in seconds
SERVER_STARTUP_MAX_ATTEMPTS = 30
SERVER_STARTUP_POLL_INTERVAL = 0.5  # seconds

# Server shutdown delay
SERVER_SHUTDOWN_DELAY = 1.0  # seconds

# Sentinel values for forcing fallback databases
FALLBACK_POSTGRES_HOST = "nonexistent.invalid"
FALLBACK_NEO4J_URI = "bolt://nonexistent.invalid:7687"
FALLBACK_REDIS_HOST = "nonexistent.invalid"


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
        """Create a data source via API."""
        url = f"{self.base_url}/api/v1/sources"
        response = await self._client.post(url, json=config, headers=self._headers())

        if response.status_code == 201:
            return response.json()["data"]
        elif response.status_code == 409:
            source_id = config["id"]
            return await self.get_source(source_id)
        else:
            response.raise_for_status()
            return {}

    async def get_source(self, source_id: str) -> dict[str, Any]:
        """Get a source by ID."""
        url = f"{self.base_url}/api/v1/sources/{source_id}"
        response = await self._client.get(url, headers=self._headers())
        response.raise_for_status()
        return response.json()["data"]

    async def trigger_pipeline(
        self,
        source_id: str,
        max_items: int | None = None,
    ) -> str:
        """Trigger pipeline for a source."""
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
        """Get pipeline task status."""
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
        """Wait for task completion."""
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
        """List articles."""
        url = f"{self.base_url}/api/v1/articles"
        params = {"page": page, "page_size": page_size}
        response = await self._client.get(url, params=params, headers=self._headers())
        response.raise_for_status()
        return response.json()["data"]


# ─────────────────────────────────────────────────────────────────────────────
# Source Configurations
# ─────────────────────────────────────────────────────────────────────────────


KNOWN_NEWSNOW_SOURCES: list[str] = [
    "36kr",
    "solidot",
    "ithome",
    "hupu",
]


RSS_SOURCES: dict[str, dict[str, Any]] = {
    "solidot": {
        "url": "https://www.solidot.org/index.rss",
        "name": "Solidot",
        "credibility": 0.70,
        "tier": 2,
    },
    "cnbeta": {
        "url": "https://plink.anyfeeder.com/cnbeta",
        "name": "CNBeta",
        "credibility": 0.70,
        "tier": 2,
    },
    "huxiu": {
        "url": "https://plink.anyfeeder.com/huxiu",
        "name": "Huxiu",
        "credibility": 0.70,
        "tier": 2,
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
        "tier": src["tier"],
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
    """Start the FastAPI server."""
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

    # Wait for server to be ready (poll health endpoint)
    import httpx

    base_url = f"http://127.0.0.1:{port}"
    client = httpx.AsyncClient(timeout=SERVER_STARTUP_TIMEOUT)

    max_attempts = SERVER_STARTUP_MAX_ATTEMPTS
    poll_interval = SERVER_STARTUP_POLL_INTERVAL

    for _attempt in range(max_attempts):
        try:
            response = await client.get(f"{base_url}/health")
            if response.status_code == 200:
                break
        except (httpx.ConnectError, httpx.ReadError):
            await asyncio.sleep(poll_interval)
    else:
        raise RuntimeError(f"Server failed to start within {max_attempts * poll_interval}s")

    await client.aclose()
    return server, task


async def setup_strategy_mode() -> ServerContext:
    """Setup strategy mode with fallback databases."""
    import container as container_module
    from config.settings import Settings
    from container import Container

    # Force fallback databases by setting invalid hosts
    os.environ["POSTGRES_HOST"] = FALLBACK_POSTGRES_HOST
    os.environ["NEO4J_URI"] = FALLBACK_NEO4J_URI
    os.environ["REDIS_HOST"] = FALLBACK_REDIS_HOST

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
    """Setup normal mode with fallback databases."""
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
    """Shutdown server and container."""
    server.should_exit = True
    await asyncio.sleep(SERVER_SHUTDOWN_DELAY)
    await container.shutdown()


# ─────────────────────────────────────────────────────────────────────────────
# Database Cleanup
# ─────────────────────────────────────────────────────────────────────────────


async def clear_databases(server_ctx: ServerContext) -> None:
    """Clear all data from test databases."""
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

    # Clear Redis dedup cache
    cache_client = server_ctx.container._redis_client
    if cache_client:
        with contextlib.suppress(Exception):
            await cache_client.delete("crawl:dedup")
            await cache_client.delete("crawl:simhash:title")
        step("Redis dedup cache cleared", True)


# ─────────────────────────────────────────────────────────────────────────────
# Test Runners
# ─────────────────────────────────────────────────────────────────────────────


async def run_all_sources(
    client: PipelineAPIClient,
    timeout: int,
    max_items: int | None = None,
    clear_db: bool = False,
) -> TestResult:
    """Run ALL sources (RSS + NewsNow) with configurable item limits."""

    phase_header("PHASE 1: Source Discovery & Creation")

    # Collect all source configs
    all_sources: list[dict[str, Any]] = []

    # RSS sources
    for source_key in RSS_SOURCES:
        try:
            config = build_rss_source_config(source_key)
            all_sources.append(config)
        except Exception as e:
            step(f"RSS source {source_key}", False, str(e))

    # NewsNow sources
    for source_id in KNOWN_NEWSNOW_SOURCES:
        config = build_newsnow_source_config(source_id)
        all_sources.append(config)

    step(f"Total sources discovered", True, f"{len(all_sources)} sources")

    # Create all sources
    created_source_ids: list[str] = []
    skipped_sources: list[tuple[str, str]] = []
    for config in all_sources:
        try:
            source = await client.create_source(config)
            created_source_ids.append(source["id"])
            step(f"Created: {source['id']}", True, f"{source.get('source_type', '?')}")
        except Exception as e:
            skipped_sources.append((config["id"], str(e)))
            step(f"Skipped: {config['id']}", False, str(e)[:80])

    if not created_source_ids:
        return TestResult(
            success=False,
            message="All sources failed to create",
            details={"skipped": skipped_sources},
        )

    phase_header(f"PHASE 2: Pipeline Execution (max_items={max_items or 'unlimited'})")

    # Trigger all pipelines sequentially
    task_map: list[tuple[str, str]] = []  # (source_id, task_id)
    failed_pipelines: list[tuple[str, str]] = []
    for source_id in created_source_ids:
        try:
            task_id = await client.trigger_pipeline(source_id, max_items=max_items)
            task_map.append((source_id, task_id))
            step(f"Pipeline triggered: {source_id}", True, f"task_id: {task_id[:8]}...")
        except Exception as e:
            failed_pipelines.append((source_id, str(e)))
            step(f"Pipeline trigger failed: {source_id}", False, str(e)[:80])

    if not task_map:
        return TestResult(
            success=False,
            message="All pipeline triggers failed",
            details={"failed": failed_pipelines},
        )

    # Wait for all tasks to complete
    phase_header("PHASE 3: Waiting for Completion")

    completed_tasks: list[tuple[str, TaskStatus]] = []
    failed_tasks: list[tuple[str, str]] = []
    for source_id, task_id in task_map:
        try:
            status = await client.wait_for_task(task_id, timeout=timeout)
            ok = status.status == "completed"
            step(
                f"{source_id}",
                ok,
                f"status={status.status} processed={status.total_processed} "
                f"completed={status.completed_count} failed={status.failed_count}",
            )
            completed_tasks.append((source_id, status))
            if not ok:
                failed_tasks.append((source_id, status.error or "unknown error"))
        except TimeoutError as e:
            failed_tasks.append((source_id, str(e)))
            step(f"{source_id}", False, f"TIMEOUT: {e}")

    # Wait for LLM processing to complete
    phase_header("PHASE 3b: Waiting for LLM Processing")
    llm_start = time.time()
    llm_timeout = timeout
    while time.time() - llm_start < llm_timeout:
        articles = await client.list_articles(page=1, page_size=1)
        total = articles.get("total", 0)
        if total == 0:
            await asyncio.sleep(5)
            continue

        # Count incomplete articles via articles API
        all_articles = await client.list_articles(page=1, page_size=min(total, 200))
        items = all_articles.get("items", [])
        incomplete = sum(1 for a in items if a.get("credibility_score") is None and a.get("body"))
        if incomplete == 0:
            step(
                "LLM processing complete",
                True,
                f"all {total} articles processed",
            )
            break
        elapsed = int(time.time() - llm_start)
        print(f"    Waiting... {incomplete} articles still processing ({elapsed}s elapsed)")
        await asyncio.sleep(10)
    else:
        print(f"    WARNING: LLM processing did not complete within {llm_timeout}s")

    phase_header("PHASE 4: Final Verification")

    # Check total articles
    articles = await client.list_articles(page=1, page_size=1)
    total = articles.get("total", 0)
    step(f"Total articles in database", total > 0, f"{total} articles")

    success_count = len(completed_tasks) - len(failed_tasks)
    total_count = len(completed_tasks)

    return TestResult(
        success=success_count > 0 and total > 0,
        message=f"{success_count}/{total_count} pipelines completed successfully",
        articles_count=total,
        details={
            "total_sources": len(created_source_ids),
            "completed": success_count,
            "failed_tasks": failed_tasks,
            "skipped_sources": skipped_sources,
            "failed_pipelines": failed_pipelines,
        },
    )


async def run_newsnow_test(
    client: PipelineAPIClient,
    source_id: str,
    max_items: int,
    timeout: int,
) -> TestResult:
    """Run NewsNow mode test."""
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
    """Run RSS mode test."""
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
    """Run Strategy mode test."""
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
# Pipeline Test Command
# ─────────────────────────────────────────────────────────────────────────────


async def cmd_test(args: argparse.Namespace) -> int:
    """Run pipeline test."""
    # Convert processing_mode string to enum
    processing_mode = ProcessingMode(args.processing_mode)
    mode_config = get_mode_config(processing_mode)

    print("=" * 60)
    print(f"  Pipeline Test: {args.mode.upper()} mode")
    print(f"  Processing: {processing_mode.value.upper()} mode")
    if mode_config:
        print(f"  Config overrides: {', '.join(k for k, v in mode_config.items() if v)}")
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
        elif args.mode == "all":
            result = await run_all_sources(
                client,
                timeout=args.timeout,
                max_items=args.max_items,
                clear_db=args.clear_db,
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


# ─────────────────────────────────────────────────────────────────────────────
# Process Pending Articles Command
# ─────────────────────────────────────────────────────────────────────────────


async def cmd_process_pending(args: argparse.Namespace) -> int:
    """Process all pending articles and sync to LadybugDB."""
    from config.settings import Settings
    from container import Container
    from core.db.models import PersistStatus
    from core.observability.logging import get_logger

    log = get_logger("process_pending")

    settings = Settings()
    container = Container().configure(settings)
    await container.startup()

    # Get services
    article_repo = container.article_repo()
    graph_writer = container.graph_writer()
    vector_repo = container.vector_repo()
    pipeline = container.pipeline()
    relational_pool = container.relational_pool()

    # Get pending articles
    async with relational_pool.session() as session:
        from sqlalchemy import text

        result = await session.execute(text("""
            SELECT CAST(id AS VARCHAR) as id, title
            FROM articles
            WHERE persist_status = 'pending'
            ORDER BY created_at
        """))
        rows = result.fetchall()

    print(f"找到 {len(rows)} 篇待处理文章")

    processed_count = 0

    for row in rows:
        article_id = row[0]
        title = row[1]

        print(f"\n处理文章: {title[:50]}...")

        try:
            # Use pipeline's process_article_phase3 method
            state = await pipeline.process_article_phase3(
                article_id=article_id, force_reprocess=True
            )

            print(f"  ✓ Phase3 完成")

            # Manual persist steps
            if not state.get("terminal"):
                article_id_uuid = uuid.UUID(article_id)
                await article_repo.upsert(state)
                await article_repo.update_persist_status(article_id_uuid, PersistStatus.PG_DONE)
                print(f"  ✓ PG 持久化完成")

                # Write to LadybugDB
                if graph_writer:
                    neo4j_ids = await graph_writer.write(state)
                    state["neo4j_ids"] = neo4j_ids
                    await article_repo.update_persist_status(
                        article_id_uuid, PersistStatus.NEO4J_DONE
                    )
                    print(f"  ✓ Neo4j/LadybugDB 持久化完成")

                # Upsert vectors
                if vector_repo and "vectors" in state:
                    vectors = state["vectors"]
                    if isinstance(vectors, dict) and "title" in vectors and "content" in vectors:
                        await vector_repo.upsert_article_vectors(
                            article_id=article_id_uuid,
                            title_embedding=vectors.get("title"),
                            content_embedding=vectors.get("content"),
                            model_id=vectors.get("model_id", "unknown"),
                        )
                        print(f"  ✓ 向量持久化完成")

            processed_count += 1

        except Exception as exc:
            print(f"  ✗ 处理失败: {exc}")
            log.error("process_pending_failed", article_id=article_id, error=str(exc))

    await container.shutdown()

    print(f"\n处理完成: {processed_count}/{len(rows)} 篇")
    return 0 if processed_count > 0 else 1


# ─────────────────────────────────────────────────────────────────────────────
# Reprocess Incomplete Articles Command
# ─────────────────────────────────────────────────────────────────────────────


async def cmd_reprocess(args: argparse.Namespace) -> int:
    """Reprocess articles with incomplete LLM fields."""
    from sqlalchemy import case, func, select

    from config.settings import Settings
    from container import Container, set_container, set_settings
    from modules.ingestion.domain.models import ArticleRaw
    from modules.storage import ArticleRepo

    # Load settings and create container
    settings = Settings()
    container = Container().configure(settings)
    set_container(container)
    set_settings(settings)

    # Initialize strategy and LLM
    await container.init_strategy()
    await container.init_llm()
    pipeline = await container.init_pipeline()
    relational_pool = container.relational_pool()
    article_repo = ArticleRepo(relational_pool)

    # Find incomplete articles
    print("Finding incomplete articles...")
    async with relational_pool.session() as session:
        from core.db.models import Article

        if args.article_id:
            # Reprocess specific article
            result = await session.execute(select(Article).where(Article.id == args.article_id))
            articles_db = result.scalars().all()
        elif args.incomplete:
            # Reprocess all incomplete articles
            result = await session.execute(
                select(Article)
                .where(Article.credibility_score.is_(None) | Article.quality_score.is_(None))
                .order_by(Article.created_at.desc())
            )
            articles_db = result.scalars().all()
        else:
            print("Error: Specify --incomplete or --article-id")
            return 1

    if not articles_db:
        print("No incomplete articles found")
        return 1

    print(f"Found {len(articles_db)} incomplete articles")

    # Convert to ArticleRaw objects
    articles = []
    article_ids = []
    for article in articles_db:
        if not article.body:
            print(f"Skipping article {article.id} - no body")
            continue

        raw = ArticleRaw(
            url=article.source_url,
            title=article.title or "",
            body=article.body,
            source=article.source_host or "reprocess",
            source_host=article.source_host or "",
            publish_time=article.publish_time,
        )
        articles.append(raw)
        article_ids.append(article.id)
        print(f"Prepared: {article.title[:50] if article.title else 'N/A'}...")

    if not articles:
        print("No articles to process (all have empty body)")
        return 1

    print(f"\nProcessing {len(articles)} articles through pipeline...")

    # Process through pipeline
    task_id = uuid.uuid4()
    states = await pipeline.process_batch(articles, article_ids=article_ids, task_id=task_id)

    # Report results
    completed = sum(1 for s in states if not s.get("terminal"))
    failed = sum(1 for s in states if s.get("terminal"))

    print(f"\nResults: {completed} completed, {failed} failed")

    # Verify final state
    async with relational_pool.session() as session:
        result = await session.execute(
            select(
                func.count(Article.id).label("total"),
                func.sum(case((Article.credibility_score.is_not(None), 1), else_=0)).label(
                    "cred_complete"
                ),
                func.sum(case((Article.quality_score.is_not(None), 1), else_=0)).label(
                    "qual_complete"
                ),
            )
        )
        row = result.one()
        print(
            f"Final state: {int(row.cred_complete or 0)}/{row.total} have credibility_score, "
            f"{int(row.qual_complete or 0)}/{row.total} have quality_score"
        )

    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Unified pipeline management script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Test modes
    uv run scripts/pipeline.py test --mode newsnow --max-items 5
    uv run scripts/pipeline.py test --mode rss --source solidot
    uv run scripts/pipeline.py test --mode all --clear-db
    uv run scripts/pipeline.py test --mode strategy

    # Processing modes
    uv run scripts/pipeline.py test --processing-mode fast    # Phase 1 only (1-2min)
    uv run scripts/pipeline.py test --processing-mode deep    # Full pipeline (5-10min)

    # Combined example
    uv run scripts/pipeline.py test --mode newsnow --processing-mode fast --max-items 10

    # Process pending articles
    uv run scripts/pipeline.py process-pending

    # Reprocess incomplete articles
    uv run scripts/pipeline.py reprocess --incomplete
    uv run scripts/pipeline.py reprocess --article-id <uuid>
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Test subcommand
    test_parser = subparsers.add_parser("test", help="Run pipeline tests")
    test_parser.add_argument(
        "--mode",
        choices=["newsnow", "rss", "strategy", "all"],
        default="newsnow",
        help="Test mode (default: newsnow)",
    )
    test_parser.add_argument(
        "--processing-mode",
        dest="processing_mode",
        choices=["fast", "deep"],
        default="deep",
        help=(
            "Processing mode: 'fast' (1-2min, Phase 1 only - classifier, cleaner, "
            "categorizer, vectorize) or 'deep' (5-10min, all 4 phases including "
            "entity extraction and quality scoring)"
        ),
    )
    test_parser.add_argument(
        "--source",
        default="solidot",
        help="RSS source name for rss mode (default: solidot)",
    )
    test_parser.add_argument(
        "--source-id",
        default="36kr",
        help="NewsNow source ID for newsnow mode (default: 36kr)",
    )
    test_parser.add_argument(
        "--max-items",
        type=int,
        default=5,
        help="Maximum items to process (default: 5)",
    )
    test_parser.add_argument(
        "--clear-db",
        action="store_true",
        help="Clear databases before testing",
    )
    test_parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Pipeline timeout in seconds (default: 300)",
    )
    test_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="API server port (default: 8000)",
    )

    # Process-pending subcommand
    subparsers.add_parser("process-pending", help="Process pending articles")

    # Reprocess subcommand
    reprocess_parser = subparsers.add_parser("reprocess", help="Reprocess incomplete articles")
    reprocess_parser.add_argument(
        "--incomplete",
        action="store_true",
        help="Reprocess all incomplete articles",
    )
    reprocess_parser.add_argument(
        "--article-id",
        type=str,
        help="Reprocess specific article by ID",
    )

    args = parser.parse_args()

    if args.command == "test":
        return asyncio.run(cmd_test(args))
    elif args.command == "process-pending":
        return asyncio.run(cmd_process_pending(args))
    elif args.command == "reprocess":
        return asyncio.run(cmd_reprocess(args))
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
