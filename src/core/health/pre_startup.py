# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pre-startup health checker for validating service availability.

This module provides health checking functionality to validate that all
required services are available before the application starts. It supports
parallel health checks with configurable timeouts and retries.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from config.settings import HealthCheckSettings, Settings

from core.observability import get_logger

log = get_logger("pre_startup_health")


@dataclass
class ServiceCheckResult:
    """Result of a single service health check.

    Attributes:
        service: Name of the service being checked.
        healthy: Whether the service is healthy.
        details: Additional details about the health check.
        error: Error message if the check failed.
        latency_ms: Time taken for the health check in milliseconds.
    """

    service: str
    healthy: bool = False
    details: list[str] = field(default_factory=list)
    error: str | None = None
    latency_ms: float | None = None


class PreStartupHealthChecker:
    """Health checker for validating service availability before startup.

    This class provides methods to check the health of various services
    (PostgreSQL, Redis, Neo4j) in parallel with configurable timeouts
    and retry logic.

    Example:
        ```python
        settings = Settings()
        checker = PreStartupHealthChecker(settings.health_check, settings)
        results = await checker.check_all()
        if not results["postgres"].healthy:
            print("PostgreSQL is not available!")
        ```
    """

    def __init__(
        self,
        health_settings: HealthCheckSettings,
        settings: Settings,
    ) -> None:
        """Initialize the health checker.

        Args:
            health_settings: Health check configuration.
            settings: Application settings containing service configurations.
        """
        self._health_settings = health_settings
        self._settings = settings
        self._results: dict[str, ServiceCheckResult] = {}

    async def check_postgres(self) -> ServiceCheckResult:
        """Check PostgreSQL connectivity and pgvector extension.

        Returns:
            ServiceCheckResult with health status and details.
        """
        import time

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        start_time = time.monotonic()
        result = ServiceCheckResult(service="postgres")

        for attempt in range(self._health_settings.max_retries):
            try:
                dsn = self._settings.postgres.dsn
                engine = create_async_engine(dsn, echo=False)

                async with engine.connect() as conn:
                    # Test basic connectivity
                    await conn.execute(text("SELECT 1"))
                    result.details.append("Connection successful")

                    # Extract database name for display
                    db_name = dsn.split("/")[-1].split("?")[0]
                    result.details.append(f"Database: {db_name}")

                    # Check pgvector extension
                    try:
                        ext_result = await conn.execute(
                            text("SELECT * FROM pg_extension WHERE extname = 'vector'")
                        )
                        if ext_result.fetchone():
                            result.details.append("pgvector extension available")
                        else:
                            result.details.append("pgvector extension not installed")
                            result.details.append("Run: CREATE EXTENSION IF NOT EXISTS vector;")
                    except Exception:
                        result.details.append("Could not check pgvector extension")

                await engine.dispose()
                result.healthy = True
                result.latency_ms = (time.monotonic() - start_time) * 1000
                return result

            except Exception as exc:
                if attempt < self._health_settings.max_retries - 1:
                    await asyncio.sleep(self._health_settings.retry_delay_seconds)
                    continue
                result.error = str(exc)
                result.details.append(f"Connection failed: {exc}")

        result.latency_ms = (time.monotonic() - start_time) * 1000
        return result

    async def check_redis(self) -> ServiceCheckResult:
        """Check Redis connectivity.

        Returns:
            ServiceCheckResult with health status and details.
        """
        import time

        from redis.asyncio import ConnectionPool, Redis

        start_time = time.monotonic()
        result = ServiceCheckResult(service="redis")

        for attempt in range(self._health_settings.max_retries):
            try:
                url = self._settings.redis.url
                pool = ConnectionPool.from_url(
                    url,
                    decode_responses=True,
                    max_connections=10,
                )
                redis_client = Redis(connection_pool=pool)

                # Test connection with ping
                await redis_client.ping()
                result.details.append("Connection successful")

                # Extract database number from URL
                db_num = url.split("/")[-1] if "/" in url else "0"
                result.details.append(f"Database: {db_num}")

                await redis_client.aclose()
                await pool.disconnect()

                result.healthy = True
                result.latency_ms = (time.monotonic() - start_time) * 1000
                return result

            except Exception as exc:
                if attempt < self._health_settings.max_retries - 1:
                    await asyncio.sleep(self._health_settings.retry_delay_seconds)
                    continue
                result.error = str(exc)
                result.details.append(f"Connection failed: {exc}")

        result.latency_ms = (time.monotonic() - start_time) * 1000
        return result

    async def check_neo4j(self) -> ServiceCheckResult:
        """Check Neo4j connectivity.

        Returns:
            ServiceCheckResult with health status and details.
        """
        import time

        from neo4j import AsyncGraphDatabase

        start_time = time.monotonic()
        result = ServiceCheckResult(service="neo4j")

        for attempt in range(self._health_settings.max_retries):
            try:
                uri = self._settings.neo4j.uri
                user = self._settings.neo4j.user
                password = self._settings.neo4j.password

                driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
                await driver.verify_connectivity()

                result.details.append("Connection successful")
                result.details.append(f"URI: {uri}")

                await driver.close()

                result.healthy = True
                result.latency_ms = (time.monotonic() - start_time) * 1000
                return result

            except Exception as exc:
                if attempt < self._health_settings.max_retries - 1:
                    await asyncio.sleep(self._health_settings.retry_delay_seconds)
                    continue
                result.error = str(exc)
                result.details.append(f"Connection failed: {exc}")

        result.latency_ms = (time.monotonic() - start_time) * 1000
        return result

    async def check_all(self) -> dict[str, ServiceCheckResult]:
        """Check all configured services in parallel.

        Returns:
            Dictionary mapping service names to their check results.
        """
        services_to_check = (
            self._health_settings.required_services + self._health_settings.optional_services
        )

        check_methods = {
            "postgres": self.check_postgres,
            "redis": self.check_redis,
            "neo4j": self.check_neo4j,
        }

        # Run all checks in parallel
        tasks = []
        service_names = []
        for service in services_to_check:
            if service in check_methods:
                tasks.append(check_methods[service]())
                service_names.append(service)
            else:
                log.warning("unknown_service_in_config", service=service)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect results
        self._results = {}
        for name, result in zip(service_names, results, strict=False):
            if isinstance(result, Exception):
                self._results[name] = ServiceCheckResult(
                    service=name,
                    healthy=False,
                    error=str(result),
                    details=[f"Check raised exception: {result}"],
                )
            else:
                self._results[name] = result

        return self._results

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of all health check results.

        Returns:
            Dictionary with summary information including overall health
            status, individual service results, and failure details.
        """
        required_healthy = all(
            self._results.get(s, ServiceCheckResult(s, False)).healthy
            for s in self._health_settings.required_services
        )

        optional_results = {
            s: self._results.get(s, ServiceCheckResult(s, False))
            for s in self._health_settings.optional_services
        }

        failed_required = [
            s
            for s in self._health_settings.required_services
            if not self._results.get(s, ServiceCheckResult(s, False)).healthy
        ]

        return {
            "overall_healthy": required_healthy,
            "required_services_healthy": required_healthy,
            "failed_required_services": failed_required,
            "results": {
                name: {
                    "healthy": r.healthy,
                    "details": r.details,
                    "error": r.error,
                    "latency_ms": r.latency_ms,
                }
                for name, r in self._results.items()
            },
            "optional_services": {name: r.healthy for name, r in optional_results.items()},
        }

    def check_and_exit(self, exit_on_failure: bool = True) -> bool:
        """Synchronous entry point that runs health checks and optionally exits.

        This method runs all health checks synchronously and prints a formatted
        report. If any required service is unhealthy and exit_on_failure is True,
        the process exits with code 1.

        Args:
            exit_on_failure: If True, exit the process when required services fail.

        Returns:
            True if all required services are healthy, False otherwise.
        """
        if not self._health_settings.pre_startup_enabled:
            log.info("pre_startup_health_check_disabled")
            return True

        # Run async checks
        results = asyncio.run(self.check_all())
        summary = self.get_summary()

        # Print report
        self._print_report(results, summary)

        if not summary["required_services_healthy"]:
            if exit_on_failure:
                log.error(
                    "pre_startup_health_check_failed",
                    failed_services=summary["failed_required_services"],
                )
                sys.exit(1)
            return False

        log.info("pre_startup_health_check_passed")
        return True

    def _print_report(
        self,
        results: dict[str, ServiceCheckResult],
        summary: dict[str, Any],
    ) -> None:
        """Print a formatted health check report.

        Args:
            results: Individual service check results.
            summary: Summary of all results.
        """
        # Use color codes for terminal output
        GREEN = "\033[92m"
        RED = "\033[91m"
        YELLOW = "\033[93m"
        RESET = "\033[0m"
        BOLD = "\033[1m"

        print(f"\n{BOLD}Pre-Startup Health Check Report{RESET}")
        print("=" * 50)

        for service, result in results.items():
            is_required = service in self._health_settings.required_services
            label = f"{service} {'(required)' if is_required else '(optional)'}"

            if result.healthy:
                print(f"{GREEN}✅ {label}{RESET}")
                for detail in result.details:
                    print(f"   {GREEN}✓{RESET} {detail}")
                if result.latency_ms:
                    print(f"   Latency: {result.latency_ms:.2f}ms")
            else:
                print(f"{RED}❌ {label}{RESET}")
                for detail in result.details:
                    if detail.startswith("✗"):
                        print(f"   {RED}{detail}{RESET}")
                    else:
                        print(f"   {detail}")
                if result.error:
                    print(f"   {RED}Error: {result.error}{RESET}")

        print("=" * 50)
        if summary["required_services_healthy"]:
            print(f"{GREEN}All required services healthy{RESET}")
        else:
            print(f"{RED}Failed services: {', '.join(summary['failed_required_services'])}{RESET}")


async def run_pre_startup_health_check(
    settings: Settings,
    exit_on_failure: bool = True,
) -> bool:
    """Run pre-startup health checks with the given settings.

    This is a convenience function that creates a PreStartupHealthChecker
    and runs the checks.

    Args:
        settings: Application settings.
        exit_on_failure: If True, exit the process when required services fail.

    Returns:
        True if all required services are healthy, False otherwise.
    """
    checker = PreStartupHealthChecker(settings.health_check, settings)
    return checker.check_and_exit(exit_on_failure=exit_on_failure)
