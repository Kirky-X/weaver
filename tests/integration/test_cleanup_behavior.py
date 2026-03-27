# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Test cleanup behavior when tests fail."""

import asyncio

import pytest


@pytest.mark.xfail(reason="Intentional test failure to verify cleanup behavior")
@pytest.mark.asyncio
async def test_cleanup_happens_on_failure():
    """Verify cleanup runs even when tests fail."""

    # Create a background task
    async def background_worker():
        while True:
            await asyncio.sleep(0.1)

    task = asyncio.create_task(background_worker())

    # Verify task is running
    await asyncio.sleep(0.05)
    assert not task.done()

    # Fail the test intentionally
    pytest.fail("Intentional test failure to verify cleanup")


@pytest.mark.asyncio
async def test_multiple_container_shutdown_calls():
    """Verify Container.shutdown() is idempotent."""
    from unittest.mock import AsyncMock, MagicMock

    from config.settings import Settings
    from container import Container

    # Create a mock container
    container = Container()
    container._settings = Settings()

    # Mock the resources
    container._postgres_pool = MagicMock()
    container._postgres_pool.shutdown = AsyncMock()

    container._redis_client = MagicMock()
    container._redis_client.shutdown = AsyncMock()

    container._pool_manager = MagicMock()
    container._pool_manager.close_all = AsyncMock()

    # Call shutdown multiple times
    await container.shutdown()
    assert container._shutdown is True

    # Second call should be a no-op
    await container.shutdown()

    # Verify shutdown was only called once
    assert container._postgres_pool.shutdown.call_count == 1
    assert container._redis_client.shutdown.call_count == 1
    assert container._pool_manager.close_all.call_count == 1
