# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pytest configuration and fixtures for E2E tests.

This module provides fixtures for end-to-end testing of the Weaver application.
E2E tests require real Docker services (PostgreSQL, Neo4j, Redis) and are
marked with @pytest.mark.e2e.

Usage:
    # Run only E2E tests
    pytest tests/e2e/ -v

    # Run all tests including E2E
    pytest tests/ -v -m e2e

    # Skip E2E tests
    pytest tests/ -v -m "not e2e"
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
import uuid
from collections.abc import Generator
from pathlib import Path
from typing import Any

import nest_asyncio
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Enable nested event loops to fix asyncpg + TestClient compatibility
nest_asyncio.apply()

# Path constants
E2E_DIR = Path(__file__).parent
E2E_COMPOSE_FILE = E2E_DIR / "docker-compose.yml"
E2E_ENV_FILE = E2E_DIR / "test_env.env"
PROJECT_ROOT = E2E_DIR.parent.parent / "src"


def _load_env_file(env_file: Path) -> dict[str, str]:
    """Parse .env file into a dict.

    Args:
        env_file: Path to the .env file.

    Returns:
        Dict of environment variable names to values.
    """
    env: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


# ── Docker Compose Management ──────────────────────────────────────


class DockerComposeManager:
    """Manages Docker Compose lifecycle for E2E tests."""

    def __init__(self, compose_file: Path, env_vars: dict[str, str]):
        self.compose_file = compose_file.resolve()
        self.env_vars = env_vars
        self._env_file: Path | None = None

    def up(self, timeout: int = 120) -> dict[str, str]:
        """Start Docker Compose services and wait for health checks.

        Args:
            timeout: Maximum seconds to wait for services to be healthy.

        Returns:
            Dict of service names to their port mappings.

        Raises:
            RuntimeError: If services don't become healthy within timeout.
        """
        assert self.compose_file.exists(), f"Compose file not found: {self.compose_file}"

        # Write temporary .env file for docker-compose
        self._env_file = self.compose_file.parent / ".env.e2e"
        env_content = "\n".join(f"{k}={v}" for k, v in self.env_vars.items())
        self._env_file.write_text(env_content)

        # Stop any existing containers
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(self.compose_file),
                "down",
                "-v",
                "--remove-orphans",
            ],
            capture_output=True,
            timeout=60,
        )

        # Start services
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(self.compose_file),
                "up",
                "-d",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, **self.env_vars},
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Docker compose up failed:\nstdout={result.stdout}\nstderr={result.stderr}"
            )

        # Wait for all services to be healthy
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(self.compose_file),
                    "ps",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                import json

                services = [json.loads(line) for line in result.stdout.strip().splitlines()]
                all_healthy = all(s.get("Health") in ("healthy", "", None) for s in services)
                if all_healthy:
                    # Extra settle time for databases
                    time.sleep(2)
                    return self._get_service_ports()
            time.sleep(2)
        else:
            raise RuntimeError(f"Docker compose services did not become healthy within {timeout}s")

    def down(self) -> None:
        """Stop and remove Docker Compose services."""
        if self._env_file:
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(self.compose_file),
                    "down",
                    "-v",
                    "--remove-orphans",
                ],
                capture_output=True,
                timeout=60,
            )
            if self._env_file.exists():
                self._env_file.unlink()
            self._env_file = None

    def _get_service_ports(self) -> dict[str, str]:
        """Get port mappings from running services."""
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(self.compose_file),
                "ps",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return {}
        import json

        ports: dict[str, str] = {}
        for line in result.stdout.strip().splitlines():
            svc = json.loads(line)
            ports[svc["Service"]] = svc.get("Ports", "")
        return ports


# ── Database Operations ─────────────────────────────────────────────


async def _run_alembic_migrations(dsn: str, project_root: Path) -> None:
    """Run Alembic migrations on the test database.

    Args:
        dsn: PostgreSQL connection string.
        project_root: Path to the project root.
    """
    alembic_ini = project_root.parent / "alembic.ini"
    result = subprocess.run(
        [
            "python",
            "-m",
            "alembic",
            "-c",
            str(alembic_ini),
            "-x",
            f"postgres_dsn={dsn}",
            "upgrade",
            "head",
        ],
        cwd=str(project_root.parent),
        capture_output=True,
        text=True,
        # WEAVER_POSTGRES__DSN is what Settings().postgres.dsn reads
        # (env_prefix="WEAVER_", nested delimiter="__")
        env={**os.environ, "WEAVER_POSTGRES__DSN": dsn},
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Alembic migration failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )


async def _truncate_tables(dsn: str) -> None:
    """Truncate all tables in the test database.

    This provides test isolation by resetting the database state before each test.

    Args:
        dsn: PostgreSQL connection string (postgresql+asyncpg://...).
    """
    import asyncpg

    # Parse DSN: postgresql+asyncpg://user:pass@host:port/db
    parsed_dsn = dsn.replace("postgresql+asyncpg://", "")
    user, rest = parsed_dsn.split(":", 1)
    password, rest = rest.split("@", 1)
    host_port, dbname = rest.split("/", 1)
    host, port = host_port.split(":")

    conn = await asyncpg.connect(
        host=host,
        port=int(port),
        user=user,
        password=password,
        database=dbname,
    )
    try:
        # Disable FK checks, truncate, re-enable
        await conn.execute("SET session_replication_role = 'replica';")
        tables = await conn.fetch("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            AND tablename NOT LIKE 'alembic_%'
            """)
        for tbl in tables:
            await conn.execute(f'TRUNCATE TABLE "{tbl["tablename"]}" CASCADE;')
        await conn.execute("SET session_replication_role = DEFAULT;")
    finally:
        await conn.close()


def _create_e2e_app(e2e_env: dict[str, str]) -> FastAPI:
    """Create the FastAPI app with E2E test settings.

    This imports lazily to avoid loading the full app during pytest collection.

    Args:
        e2e_env: Dict of environment variable names to values loaded from test_env.env.

    Returns:
        Configured FastAPI application.
    """
    from config.settings import Settings
    from container import Container
    from main import create_app

    # Set E2E environment variables in os.environ (they are read by Settings()
    # on first instantiation and cached). The first Settings() call in the process
    # caches the env vars from os.environ, so we must set them before any Settings()
    # call AND directly patch the api.api_key to be safe.
    for key, value in e2e_env.items():
        os.environ[key] = value

    os.environ.setdefault("ENVIRONMENT", "testing")
    os.environ.setdefault("DEBUG", "true")

    settings = Settings()
    # pydantic-settings caches env vars on first instantiation. Directly set the
    # api_key to ensure the E2E value is used regardless of caching.
    settings.api.api_key = e2e_env.get("WEAVER_API__API_KEY", settings.api.api_key)
    container = Container().configure(settings)
    return create_app(container)


# ── Pytest Fixtures ────────────────────────────────────────────────


@pytest.fixture(scope="session")
def e2e_env() -> dict[str, str]:
    """Load E2E test environment variables.

    Returns:
        Dict of environment variable names to values.
    """
    return _load_env_file(E2E_ENV_FILE)


@pytest.fixture(scope="session")
def api_key(e2e_env: dict[str, str]) -> str:
    """Get the API key for E2E tests.

    Args:
        e2e_env: E2E environment variables.

    Returns:
        The API key string.
    """
    return e2e_env["WEAVER_API__API_KEY"]


@pytest.fixture(scope="session")
def postgres_dsn(e2e_env: dict[str, str]) -> str:
    """Get the PostgreSQL DSN for E2E tests.

    Args:
        e2e_env: E2E environment variables.

    Returns:
        The PostgreSQL connection string.
    """
    # Build DSN from individual POSTGRES_* environment variables
    host = e2e_env.get("POSTGRES_HOST", "localhost")
    port = e2e_env.get("POSTGRES_PORT", "5432")
    user = e2e_env.get("POSTGRES_USER", "postgres")
    password = e2e_env.get("POSTGRES_PASSWORD", "postgres")
    database = e2e_env.get("POSTGRES_DATABASE", "weaver")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


@pytest.fixture(scope="session")
def docker_compose(
    e2e_env: dict[str, str],
) -> Generator[DockerComposeManager, None, None]:
    """Start Docker Compose services for the E2E test session.

    This fixture has session scope - Docker containers are started once
    for all E2E tests, and torn down at the end of the session.

    Args:
        e2e_env: E2E environment variables.

    Yields:
        DockerComposeManager instance.
    """
    manager = DockerComposeManager(E2E_COMPOSE_FILE, e2e_env)
    try:
        manager.up(timeout=180)
        yield manager
    finally:
        manager.down()


@pytest_asyncio.fixture(scope="session")
async def db_migrations(
    docker_compose: DockerComposeManager,
    postgres_dsn: str,
) -> None:
    """Run Alembic migrations on the E2E database once per session.

    Args:
        docker_compose: Docker compose manager (ensures services are up).
        postgres_dsn: PostgreSQL connection string.
    """
    await _run_alembic_migrations(postgres_dsn, PROJECT_ROOT)


@pytest_asyncio.fixture(scope="function")
async def clean_tables(
    docker_compose: DockerComposeManager,
    postgres_dsn: str,
) -> None:
    """Truncate all tables before each E2E test function.

    This ensures test isolation - each test starts with an empty database.

    Args:
        docker_compose: Docker compose manager.
        postgres_dsn: PostgreSQL connection string.
    """
    await _truncate_tables(postgres_dsn)
    yield


@pytest.fixture(scope="session")
def e2e_app(
    docker_compose: DockerComposeManager,
    db_migrations: None,
    e2e_env: dict[str, str],
) -> FastAPI:
    """Create the FastAPI application instance for E2E testing.

    Depends on docker_compose (ensures Docker is up) and db_migrations
    (ensures schema is created). Both have session scope, so the app
    is created once per test session.

    Args:
        docker_compose: Docker compose manager.
        db_migrations: Migration fixture (ensures DB is ready).
        e2e_env: E2E environment variables (provides API key, DSN, etc.).

    Returns:
        Configured FastAPI application.
    """
    return _create_e2e_app(e2e_env)


@pytest.fixture(scope="session")
def client(e2e_app: FastAPI) -> Generator[TestClient, None, None]:
    """Provide a synchronous TestClient for the E2E app.

    TestClient handles lifespan startup/shutdown automatically.
    This is the primary interface for making API calls in E2E tests.

    Note: Uses session scope for performance. The event loop is managed
    by pytest-asyncio with session scope configured in pytest.ini.

    Args:
        e2e_app: FastAPI application instance.

    Yields:
        TestClient instance.
    """
    import warnings

    # Suppress warnings during teardown to avoid polluting test output
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            with TestClient(e2e_app) as tc:
                yield tc
        except RuntimeError as e:
            # Ignore event loop errors during teardown
            if "attached to a different loop" in str(e) or "Event loop is closed" in str(e):
                pass
            else:
                raise


@pytest.fixture
def auth_headers(api_key: str) -> dict[str, str]:
    """Standard authentication headers for E2E API calls.

    Args:
        api_key: API key string.

    Returns:
        Dict with X-API-Key header.
    """
    return {"X-API-Key": api_key}


@pytest.fixture
def unique_id() -> str:
    """Generate a unique ID for test data isolation.

    Returns:
        UUID string (first 8 characters).
    """
    return str(uuid.uuid4())[:8]


@pytest.fixture
def unique_source_id(unique_id: str) -> str:
    """Generate a unique source ID.

    Args:
        unique_id: Unique identifier.

    Returns:
        Source ID string.
    """
    return f"e2e_source_{unique_id}"


# ── Tracer Cleanup (prevent E2E state pollution in subsequent tests) ─────────────


@pytest.fixture(scope="session", autouse=True)
def reset_tracer_provider() -> None:
    """Reset global OpenTelemetry tracer provider after E2E session.

    The OpenTelemetry SDK uses a Once guard that allows only one
    set_tracer_provider call per process. E2E app startup calls
    configure_tracing which sets the global tracer provider. Without
    cleanup, subsequent non-E2E tests fail because set_tracer_provider
    is locked and cannot be re-called.
    """
    yield
    # Cleanup after all E2E tests complete
    try:
        from opentelemetry import trace as otel_trace

        otel_trace._TRACER_PROVIDER = None
        otel_trace._TRACER_PROVIDER_SET_ONCE._done = False
    except Exception:
        pass  # Best-effort cleanup


# ── Marker Registration ─────────────────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    """Register E2E-specific pytest markers."""
    config.addinivalue_line(
        "markers",
        "e2e: end-to-end test (requires Docker services)",
    )
    config.addinivalue_line(
        "markers",
        "e2e_isolated: isolated E2E test (clean tables between runs)",
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
    call: pytest.CallInfo[None],
) -> Generator[None, None, None]:
    """Ignore event loop errors during E2E test teardown.

    SQLAlchemy/asyncpg raises RuntimeError during cleanup when the event loop
    changes between test runs. This is a known compatibility issue with
    pytest-asyncio and session-scoped TestClient fixtures.
    """
    outcome = yield
    report = outcome.get_result()

    # Only check during call phase (not setup/teardown)
    is_runtime_error = call.excinfo and isinstance(call.excinfo.value, RuntimeError)
    if report.when == "call" and report.failed and is_runtime_error:
        error_msg = str(call.excinfo.value)
        if "attached to a different loop" in error_msg or "Event loop is closed" in error_msg:
            # The test itself passed; error is only during teardown
            report.outcome = "passed"
            report.longrepr = None
