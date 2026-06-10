# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Root pytest configuration - minimal, no heavy resources.

This conftest only provides:
1. Environment setup
2. Pytest markers configuration
3. Test collection hooks
4. Session cleanup

All mock fixtures are in tests/unit/conftest.py
All real resource fixtures are in tests/integration/conftest.py
"""

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load environment variables from .env file before any tests run
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=True)

# Set test-specific environment variables
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")


# ────────────────────────────────────────────────────────────
# Pytest configuration hooks
# ────────────────────────────────────────────────────────────


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "asyncio: mark test as async")
    config.addinivalue_line("markers", "unit: mark test as unit test")
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "e2e: mark test as end-to-end test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line(
        "markers", "no_parallel: mark test as not suitable for parallel execution"
    )
    config.addinivalue_line("markers", "describe: mark test class as describing a feature")
    config.addinivalue_line("markers", "it: mark test method as a specific behavior")


def pytest_collection_modifyitems(config, items):
    """Add markers to tests based on file location."""
    for item in items:
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        elif "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "e2e" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)


# ────────────────────────────────────────────────────────────
# Event loop and session cleanup
# ────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case.

    This is required for session-scoped async fixtures to work with pytest-asyncio.
    """
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


async def _cancel_all_tasks() -> None:
    """Cancel all pending asyncio tasks from the current event loop."""
    loop = asyncio.get_running_loop()
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]

    if not tasks:
        return

    for task in tasks:
        task.cancel()

    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5.0)
    except (TimeoutError, Exception):
        pass


def pytest_sessionfinish(session, exitstatus):
    """Global cleanup hook that runs after all tests complete."""
    import sys

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(_cancel_all_tasks(), loop).result(timeout=10)
        else:
            loop.run_until_complete(_cancel_all_tasks())
    except RuntimeError:
        pass
    except Exception:
        pass
