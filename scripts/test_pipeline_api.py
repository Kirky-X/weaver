#!/usr/bin/env python
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Test the complete pipeline via HTTP API with DuckDB + LadybugDB fallback.

This script:
1. Starts the API server with fallback databases
2. Creates a NewsNow source
3. Triggers the pipeline via HTTP API
4. Monitors progress
5. Verifies results in the database
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

import httpx

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import container as container_module
from config.settings import Settings
from container import Container


async def start_server(container: Container, host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the FastAPI server."""
    import uvicorn

    from api.main import create_app

    app = create_app()
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)

    # Run in background
    task = asyncio.create_task(server.serve())

    # Wait for server to start
    await asyncio.sleep(2)

    return server, task


async def create_newsnow_source(
    client: httpx.AsyncClient, base_url: str, api_key: str, source_id: str
) -> dict:
    """Create a NewsNow source via API."""
    url = f"{base_url}/api/v1/sources"

    payload = {
        "id": f"newsnow-{source_id}",
        "name": f"NewsNow {source_id}",
        "url": f"https://www.newsnow.world/api/s?id={source_id}",
        "source_type": "newsnow",
        "enabled": True,
        "interval_minutes": 30,
    }

    headers = {"X-API-Key": api_key}

    response = await client.post(url, json=payload, headers=headers)
    if response.status_code == 201:
        print(f"Created source: newsnow-{source_id}")
        return response.json()["data"]
    elif response.status_code == 409:
        print(f"Source already exists: newsnow-{source_id}")
        return await get_source(client, base_url, api_key, f"newsnow-{source_id}")
    else:
        raise Exception(f"Failed to create source: {response.text}")


async def get_source(
    client: httpx.AsyncClient, base_url: str, api_key: str, source_id: str
) -> dict:
    """Get a source by ID."""
    url = f"{base_url}/api/v1/sources/{source_id}"
    headers = {"X-API-Key": api_key}

    response = await client.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()["data"]
    else:
        raise Exception(f"Failed to get source: {response.text}")


async def trigger_pipeline(
    client: httpx.AsyncClient, base_url: str, api_key: str, source_id: str, max_items: int = 5
) -> str:
    """Trigger the pipeline for a specific source."""
    url = f"{base_url}/api/v1/pipeline/trigger"

    payload = {
        "source_id": source_id,
        "max_items": max_items,
        "force": True,
    }

    headers = {"X-API-Key": api_key}

    print(f"Triggering pipeline for source: {source_id}")
    response = await client.post(url, json=payload, headers=headers)

    if response.status_code == 200:
        data = response.json()["data"]
        print(f"Pipeline triggered, task_id: {data['task_id']}")
        return data["task_id"]
    else:
        raise Exception(f"Failed to trigger pipeline: {response.text}")


async def wait_for_task(
    client: httpx.AsyncClient, base_url: str, api_key: str, task_id: str, timeout: int = 300
) -> dict:
    """Wait for a pipeline task to complete."""
    url = f"{base_url}/api/v1/pipeline/tasks/{task_id}"
    headers = {"X-API-Key": api_key}

    start_time = time.time()

    while time.time() - start_time < timeout:
        response = await client.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()["data"]
            status = data["status"]

            if status in ["completed", "failed"]:
                print(f"Task {task_id} finished with status: {status}")
                return data

            print(
                f"Task {task_id} status: {status}, processed: {data.get('total_processed', 0)}, "
                f"completed: {data.get('completed_count', 0)}, failed: {data.get('failed_count', 0)}"
            )

        await asyncio.sleep(5)

    raise TimeoutError(f"Task {task_id} did not complete within {timeout} seconds")


async def check_database_results(container: Container) -> dict:
    """Check results in the database."""
    strategy = container._strategy

    results = {
        "relational_type": strategy.relational_type,
        "graph_type": strategy.graph_type,
        "articles": 0,
        "entities": 0,
    }

    # Check articles in relational DB
    from core.db.duckdb_pool import DuckDBPool

    if isinstance(strategy.relational_pool, DuckDBPool):

        conn = strategy.relational_pool._conn
        count_result = conn.execute("SELECT COUNT(*) FROM articles").fetchone()
        results["articles"] = count_result[0] if count_result else 0
        print(f"Articles in DuckDB: {results['articles']}")
    else:
        # PostgreSQL
        async with strategy.relational_pool.session() as session:
            from sqlalchemy import func, select

            from core.db.models import Article

            result = await session.execute(select(func.count(Article.id)))
            results["articles"] = result.scalar() or 0
            print(f"Articles in PostgreSQL: {results['articles']}")

    # Check entities in graph DB
    from core.db.ladybug_pool import LadybugPool

    if isinstance(strategy.graph_pool, LadybugPool):
        # LadybugDB

        conn = strategy.graph_pool._conn
        cursor = conn.execute("SELECT COUNT(*) FROM entities")
        results["entities"] = cursor.fetchone()[0] or 0
        print(f"Entities in LadybugDB: {results['entities']}")
    elif strategy.graph_pool is not None:
        # Neo4j

        async with strategy.graph_pool.driver.session() as session:
            result = await session.run("MATCH (e:Entity) RETURN count(e) as count")
            record = await result.single()
            results["entities"] = record["count"] if record else 0
            print(f"Entities in Neo4j: {results['entities']}")

    return results


async def main():
    parser = argparse.ArgumentParser(description="Test complete pipeline via HTTP API")
    parser.add_argument("--source-id", default="36kr", help="NewsNow source ID (default: 36kr)")
    parser.add_argument(
        "--max-items", type=int, default=5, help="Maximum items to process (default: 5)"
    )
    parser.add_argument("--port", type=int, default=8000, help="API server port (default: 8000)")
    parser.add_argument(
        "--timeout", type=int, default=300, help="Pipeline timeout in seconds (default: 300)"
    )
    parser.add_argument(
        "--use-fallback",
        action="store_true",
        help="Force use of fallback databases (DuckDB + LadybugDB)",
    )

    args = parser.parse_args()

    # Set environment variables for fallback databases if requested
    if args.use_fallback:
        os.environ["POSTGRES_HOST"] = "nonexistent.invalid"
        os.environ["REDIS_HOST"] = "nonexistent.invalid"
        os.environ["NEO4J_URI"] = "bolt://nonexistent.invalid:7687"
        print("Using fallback databases (DuckDB + LadybugDB + CashewsRedis)")

    # Initialize container
    print("Initializing container...")
    settings = Settings()
    container = Container().configure(settings)
    await container.startup()
    container_module._container = container

    strategy = container._strategy
    print(f"Database strategy:")
    print(f"  - Relational: {strategy.relational_type}")
    print(f"  - Graph: {strategy.graph_type}")
    print(f"  - Redis: {type(container._redis_client).__name__}")

    try:
        # Get API key
        api_key = settings.api.get_api_key()
        base_url = f"http://127.0.0.1:{args.port}"

        # Start server in background
        print(f"\nStarting API server on {base_url}...")
        import uvicorn

        from main import create_app

        app = create_app(container)
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=args.port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)

        # Run server in background task
        server_task = asyncio.create_task(server.serve())
        # Keep reference to prevent garbage collection
        _ = server_task

        # Wait for server to start
        await asyncio.sleep(3)

        # Create HTTP client
        async with httpx.AsyncClient(timeout=300.0) as client:
            # Create NewsNow source
            print(f"\nCreating NewsNow source: {args.source_id}")
            source = await create_newsnow_source(client, base_url, api_key, args.source_id)
            source_full_id = f"newsnow-{args.source_id}"

            # Trigger pipeline
            print(f"\nTriggering pipeline (max_items={args.max_items})...")
            task_id = await trigger_pipeline(
                client, base_url, api_key, source_full_id, args.max_items
            )

            # Wait for completion
            print(f"\nWaiting for pipeline to complete...")
            task_result = await wait_for_task(client, base_url, api_key, task_id, args.timeout)

            print(f"\nPipeline result:")
            print(f"  - Status: {task_result['status']}")
            print(f"  - Total processed: {task_result.get('total_processed', 0)}")
            print(f"  - Completed: {task_result.get('completed_count', 0)}")
            print(f"  - Failed: {task_result.get('failed_count', 0)}")
            if task_result.get("error"):
                print(f"  - Error: {task_result['error']}")

            # Check database results
            print(f"\nChecking database results...")
            db_results = await check_database_results(container)

            print(f"\nFinal results:")
            print(f"  - Database: {db_results['relational_type']} + {db_results['graph_type']}")
            print(f"  - Articles: {db_results['articles']}")
            print(f"  - Entities: {db_results['entities']}")

        # Shutdown server
        server.should_exit = True
        await asyncio.sleep(1)

    finally:
        print("\nShutting down...")
        await container.shutdown()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
