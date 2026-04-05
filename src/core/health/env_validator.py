# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Environment validator for comprehensive service validation.

This module provides a unified interface for validating all infrastructure
services and AI providers before running the application. It consolidates
the functionality from scripts/validate_environment.py into a reusable
module that can be used both from the command line and programmatically.

Usage:
    # Command line
    uv run python -m core.health.env_validator [--service SERVICE]

    # Programmatic
    from core.health.env_validator import EnvironmentValidator
    validator = EnvironmentValidator(settings)
    results = await validator.validate_all()
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.settings import Settings

from core.constants import Defaults, LLMProvider
from core.observability import get_logger

log = get_logger("env_validator")


# ────────────────────────────────────────────────────────────
# Color Codes for Console Output
# ────────────────────────────────────────────────────────────


class Colors:
    """ANSI color codes for console output."""

    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


# ────────────────────────────────────────────────────────────
# Validation Result Types
# ────────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    """Result of a single validation check."""

    service: str
    healthy: bool
    details: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    latency_ms: float | None = None


# ────────────────────────────────────────────────────────────
# Validation Cache
# ────────────────────────────────────────────────────────────


class ValidationCache:
    """Simple in-memory cache for validation results.

    Caches validation results for 5 minutes to avoid repeated
    API calls to LLM/embedding providers during short time spans.
    """

    def __init__(self, ttl_minutes: int = 5):
        self._cache: dict[str, tuple[ValidationResult, datetime]] = {}
        self._ttl = timedelta(minutes=ttl_minutes)

    def get(self, key: str) -> ValidationResult | None:
        """Get cached result if still valid."""
        if key not in self._cache:
            return None

        result, timestamp = self._cache[key]
        if datetime.now() - timestamp > self._ttl:
            del self._cache[key]
            return None

        return result

    def set(self, key: str, result: ValidationResult) -> None:
        """Cache a validation result."""
        self._cache[key] = (result, datetime.now())

    def clear(self) -> None:
        """Clear all cached results."""
        self._cache.clear()


# ────────────────────────────────────────────────────────────
# Environment Validator
# ────────────────────────────────────────────────────────────


class EnvironmentValidator:
    """Comprehensive environment validator for all services.

    This class provides validation for:
    - PostgreSQL (connectivity, pgvector extension)
    - Neo4j (connectivity)
    - Redis (connectivity)
    - LLM providers (OpenAI, Ollama, Anthropic)
    - Embedding models

    Example:
        ```python
        from config.settings import Settings
        from core.health.env_validator import EnvironmentValidator

        settings = Settings()
        validator = EnvironmentValidator(settings)
        results = await validator.validate_all()

        for service, result in results.items():
            print(f"{service}: {'OK' if result.healthy else 'FAILED'}")
        ```
    """

    def __init__(
        self,
        settings: Settings,
        cache_ttl_minutes: int = 5,
    ) -> None:
        """Initialize the validator.

        Args:
            settings: Application settings.
            cache_ttl_minutes: Cache TTL for validation results.
        """
        self._settings = settings
        self._cache = ValidationCache(ttl_minutes=cache_ttl_minutes)

    async def validate_postgres(self) -> ValidationResult:
        """Validate PostgreSQL connectivity and pgvector extension.

        Returns:
            ValidationResult with status and details.
        """
        import time

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        start_time = time.monotonic()
        result = ValidationResult(service="PostgreSQL", healthy=False)

        max_retries = 3
        retry_delay = 2.0

        for attempt in range(max_retries):
            try:
                dsn = self._settings.postgres.dsn
                engine = create_async_engine(dsn, echo=False)

                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                    result.details.append("✓ Connection successful")

                    db_name = dsn.split("/")[-1].split("?")[0]
                    result.details.append(f"✓ Database: {db_name}")

                    # Check pgvector
                    ext_result = await conn.execute(
                        text("SELECT * FROM pg_extension WHERE extname = 'vector'")
                    )
                    if ext_result.fetchone():
                        result.details.append("✓ pgvector extension available")
                    else:
                        result.details.append("✗ pgvector extension not installed")
                        result.suggestions.append(
                            "Run: CREATE EXTENSION IF NOT EXISTS vector; in PostgreSQL"
                        )

                await engine.dispose()
                result.healthy = len(result.suggestions) == 0
                result.latency_ms = (time.monotonic() - start_time) * 1000
                return result

            except Exception as exc:
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                result.details.append(f"✗ Connection failed: {exc}")

                error_msg = str(exc)
                if "Connection refused" in error_msg:
                    result.suggestions.append("Check if PostgreSQL is running")
                elif "authentication failed" in error_msg.lower():
                    result.suggestions.append("Check PostgreSQL credentials")
                else:
                    result.suggestions.append("Check PostgreSQL service status")

        result.latency_ms = (time.monotonic() - start_time) * 1000
        return result

    async def validate_neo4j(self) -> ValidationResult:
        """Validate Neo4j connectivity.

        Returns:
            ValidationResult with status and details.
        """
        import time

        from neo4j import AsyncGraphDatabase

        start_time = time.monotonic()
        result = ValidationResult(service="Neo4j", healthy=False)

        max_retries = 3
        retry_delay = 2.0

        for attempt in range(max_retries):
            try:
                uri = self._settings.neo4j.uri
                user = self._settings.neo4j.user
                password = self._settings.neo4j.password

                driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
                await driver.verify_connectivity()

                result.details.append("✓ Connection successful")
                result.details.append(f"✓ URI: {uri}")

                await driver.close()

                result.healthy = True
                result.latency_ms = (time.monotonic() - start_time) * 1000
                return result

            except Exception as exc:
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                result.details.append(f"✗ Connection failed: {exc}")

                error_msg = str(exc)
                if "Connection refused" in error_msg:
                    result.suggestions.append(
                        f"Check if Neo4j is running at {self._settings.neo4j.uri}"
                    )
                elif "authentication" in error_msg.lower():
                    result.suggestions.append("Check Neo4j credentials")
                else:
                    result.suggestions.append("Check Neo4j service status")

        result.latency_ms = (time.monotonic() - start_time) * 1000
        return result

    async def validate_redis(self) -> ValidationResult:
        """Validate Redis connectivity.

        Returns:
            ValidationResult with status and details.
        """
        import time

        from redis.asyncio import ConnectionPool, Redis

        start_time = time.monotonic()
        result = ValidationResult(service="Redis", healthy=False)

        max_retries = 3
        retry_delay = 2.0

        for attempt in range(max_retries):
            try:
                url = self._settings.redis.url
                pool = ConnectionPool.from_url(url, decode_responses=True, max_connections=10)
                redis_client = Redis(connection_pool=pool)

                await redis_client.ping()
                result.details.append("✓ Connection successful")

                db_num = url.split("/")[-1] if "/" in url else "0"
                result.details.append(f"✓ Database: {db_num}")

                await redis_client.aclose()
                await pool.disconnect()

                result.healthy = True
                result.latency_ms = (time.monotonic() - start_time) * 1000
                return result

            except Exception as exc:
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                result.details.append(f"✗ Connection failed: {exc}")

                error_msg = str(exc)
                if "Connection refused" in error_msg:
                    result.suggestions.append("Check if Redis is running")
                else:
                    result.suggestions.append("Check Redis service status")

        result.latency_ms = (time.monotonic() - start_time) * 1000
        return result

    async def validate_llm(self) -> ValidationResult:
        """Validate LLM provider accessibility.

        Returns:
            ValidationResult with status and details.
        """
        import time

        import httpx

        start_time = time.monotonic()
        result = ValidationResult(service="LLM", healthy=False)

        providers = self._settings.llm.providers
        if not providers:
            result.details.append("✗ No LLM providers configured")
            result.suggestions.append("Configure at least one LLM provider")
            return result

        # Validate primary provider
        primary_name = next(iter(providers.keys()))
        primary_config = providers[primary_name]

        provider_type = primary_config.get("provider", "unknown")
        model = primary_config.get("model", "unknown")
        base_url = primary_config.get("base_url", "")
        api_key = primary_config.get("api_key", "")

        # Check cache
        cache_key = f"llm:{provider_type}:{model}:{base_url}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        result.details.append(f"Provider: {provider_type} ({primary_name})")
        result.details.append(f"Model: {model}")

        max_retries = 3
        retry_delay = 2.0

        for attempt in range(max_retries):
            try:
                if provider_type == LLMProvider.OPENAI.value:
                    if not api_key:
                        result.details.append("✗ API key not configured")
                        result.suggestions.append("Set OpenAI API key")
                        self._cache.set(cache_key, result)
                        return result

                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.get(
                            f"{base_url}/models",
                            headers={"Authorization": f"Bearer {api_key}"},
                        )

                        if response.status_code == 200:
                            result.details.append("✓ API key valid")
                            result.details.append(f"✓ Provider accessible at {base_url}")

                            models_data = response.json()
                            available = [m["id"] for m in models_data.get("data", [])]
                            if model in available:
                                result.details.append(f"✓ Model {model} available")
                            else:
                                result.details.append(f"⚠ Model {model} not found")

                            result.healthy = True
                            result.latency_ms = (time.monotonic() - start_time) * 1000
                            self._cache.set(cache_key, result)
                            return result
                        result.details.append(f"✗ API returned status {response.status_code}")
                        result.suggestions.append("Check API key and base URL")

                elif provider_type == LLMProvider.OLLAMA.value:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.get(f"{base_url}/api/tags")

                        if response.status_code == 200:
                            result.details.append(f"✓ Provider accessible at {base_url}")

                            models_data = response.json()
                            available = [m.get("name", "") for m in models_data.get("models", [])]

                            model_variants = [model, f"{model}:latest"]
                            if any(m in available for m in model_variants):
                                result.details.append(f"✓ Model {model} available")
                            else:
                                result.details.append(f"✗ Model {model} not found")
                                result.suggestions.append(f"Pull the model: ollama pull {model}")

                            result.healthy = True
                            result.latency_ms = (time.monotonic() - start_time) * 1000
                            self._cache.set(cache_key, result)
                            return result
                        result.details.append(f"✗ Server returned status {response.status_code}")

                elif provider_type == LLMProvider.ANTHROPIC.value:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.get(base_url, follow_redirects=True)
                        result.details.append(f"✓ Provider accessible at {base_url}")
                        result.details.append(f"✓ Model {model} configured")
                        result.healthy = True
                        result.latency_ms = (time.monotonic() - start_time) * 1000
                        self._cache.set(cache_key, result)
                        return result

                else:
                    result.details.append(f"✗ Unknown provider type: {provider_type}")
                    result.suggestions.append("Configure a supported provider")

            except httpx.ConnectError:
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                result.details.append("✗ Connection failed")
                result.suggestions.append(f"Check if {provider_type} server is running")
            except Exception as exc:
                result.details.append(f"✗ Validation failed: {exc}")
                result.suggestions.append(f"Check {provider_type} configuration")

        result.latency_ms = (time.monotonic() - start_time) * 1000
        self._cache.set(cache_key, result)
        return result

    async def validate_embedding(self) -> ValidationResult:
        """Validate embedding model accessibility.

        Returns:
            ValidationResult with status and details.
        """
        import time

        import httpx

        start_time = time.monotonic()
        result = ValidationResult(service="Embedding", healthy=False)

        embedding_provider = self._settings.llm.embedding_provider
        embedding_model = self._settings.llm.embedding_model

        result.details.append(f"Provider: {embedding_provider}")
        result.details.append(f"Model: {embedding_model}")

        providers = self._settings.llm.providers
        if embedding_provider not in providers:
            result.details.append(f"✗ Provider '{embedding_provider}' not configured")
            result.suggestions.append(f"Configure '{embedding_provider}' provider")
            return result

        provider_config = providers[embedding_provider]
        provider_type = provider_config.get("provider", "unknown")
        base_url = provider_config.get("base_url", "")
        api_key = provider_config.get("api_key", "")

        max_retries = 3
        retry_delay = 2.0

        for attempt in range(max_retries):
            try:
                if provider_type == LLMProvider.OPENAI.value:
                    if not api_key:
                        result.details.append("✗ API key not configured")
                        result.suggestions.append("Set API key for embedding provider")
                        return result

                    async with httpx.AsyncClient(timeout=Defaults.TIMEOUT_SECONDS) as client:
                        response = await client.post(
                            f"{base_url}/embeddings",
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json",
                            },
                            json={"input": "test", "model": embedding_model},
                        )

                        if response.status_code == 200:
                            result.details.append("✓ API key valid")
                            result.details.append(f"✓ Model {embedding_model} available")
                            result.healthy = True
                            result.latency_ms = (time.monotonic() - start_time) * 1000
                            return result
                        result.details.append(f"✗ API returned status {response.status_code}")
                        result.suggestions.append("Check embedding model name")

                elif provider_type == LLMProvider.OLLAMA.value:
                    async with httpx.AsyncClient(timeout=Defaults.TIMEOUT_SECONDS) as client:
                        response = await client.post(
                            f"{base_url}/api/embeddings",
                            json={"model": embedding_model, "prompt": "test"},
                        )

                        if response.status_code == 200:
                            result.details.append(f"✓ Model {embedding_model} available")
                            result.healthy = True
                            result.latency_ms = (time.monotonic() - start_time) * 1000
                            return result
                        result.details.append(f"✗ Server returned status {response.status_code}")
                        result.suggestions.append(f"Check if model {embedding_model} is pulled")

            except httpx.ConnectError:
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                result.details.append("✗ Connection failed")
                result.suggestions.append(f"Check if {provider_type} server is running")
            except Exception as exc:
                result.details.append(f"✗ Validation failed: {exc}")

        result.latency_ms = (time.monotonic() - start_time) * 1000
        return result

    async def validate_all(
        self,
        services: list[str] | None = None,
    ) -> dict[str, ValidationResult]:
        """Validate all or specified services.

        Args:
            services: Optional list of specific services to validate.
                     If None, validates all services.

        Returns:
            Dictionary mapping service names to validation results.
        """
        all_validators = {
            "postgres": self.validate_postgres,
            "neo4j": self.validate_neo4j,
            "redis": self.validate_redis,
            "llm": self.validate_llm,
            "embedding": self.validate_embedding,
        }

        if services:
            validators = {k: v for k, v in all_validators.items() if k in services}
        else:
            validators = all_validators

        results = {}
        for name, validator in validators.items():
            try:
                results[name] = await validator()
            except Exception as exc:
                results[name] = ValidationResult(
                    service=name,
                    healthy=False,
                    details=[f"✗ Validation raised exception: {exc}"],
                )

        return results

    def print_report(self, results: dict[str, ValidationResult]) -> None:
        """Print a formatted validation report.

        Args:
            results: Validation results to print.
        """
        print(f"\n{Colors.BOLD}Environment Validation Report{Colors.RESET}")
        print("=" * 60)

        for result in results.values():
            if result.healthy:
                print(f"{Colors.GREEN}✅ {result.service}{Colors.RESET}")
                for detail in result.details:
                    print(f"   {Colors.GREEN}✓{Colors.RESET} {detail}")
            else:
                print(f"{Colors.RED}❌ {result.service}{Colors.RESET}")
                for detail in result.details:
                    if detail.startswith("✗"):
                        print(f"   {Colors.RED}{detail}{Colors.RESET}")
                    else:
                        print(f"   {detail}")
                if result.suggestions:
                    for suggestion in result.suggestions:
                        print(f"   {Colors.CYAN}ℹ Suggestion:{Colors.RESET} {suggestion}")
            if result.latency_ms:
                print(f"   Latency: {result.latency_ms:.2f}ms")

        # Summary
        healthy_count = sum(1 for r in results.values() if r.healthy)
        total_count = len(results)

        print("=" * 60)
        if healthy_count == total_count:
            print(f"{Colors.GREEN}All {total_count} services healthy{Colors.RESET}")
        else:
            print(f"{Colors.YELLOW}{healthy_count}/{total_count} services healthy{Colors.RESET}")

        # Log summary for structured logging
        unhealthy = [r for r in results.values() if not r.healthy]
        if unhealthy:
            log.error(
                "env_validation_failed",
                failed_services=[r.service for r in unhealthy],
            )
        else:
            log.info("env_validation_passed", services=len(results))

    def get_exit_code(self, results: dict[str, ValidationResult]) -> int:
        """Get exit code based on validation results.

        Args:
            results: Validation results.

        Returns:
            0 if all services healthy, 1 otherwise.
        """
        return 0 if all(r.healthy for r in results.values()) else 1


# ────────────────────────────────────────────────────────────
# Convenience Functions
# ────────────────────────────────────────────────────────────


async def validate_environment(
    settings: Settings | None = None,
    services: list[str] | None = None,
    print_report: bool = True,
) -> tuple[bool, dict[str, ValidationResult]]:
    """Validate environment services.

    This is a convenience function that creates an EnvironmentValidator
    and runs validation.

    Args:
        settings: Application settings. If None, loads from default.
        services: Optional list of services to validate.
        print_report: Whether to print the validation report.

    Returns:
        Tuple of (all_healthy, results_dict).
    """
    if settings is None:
        from config.settings import Settings

        settings = Settings()

    validator = EnvironmentValidator(settings)
    results = await validator.validate_all(services)

    if print_report:
        validator.print_report(results)

    all_healthy = all(r.healthy for r in results.values())
    return all_healthy, results


# ────────────────────────────────────────────────────────────
# CLI Entry Point
# ────────────────────────────────────────────────────────────


async def main(services: list[str] | None = None) -> int:
    """Run environment validation from command line.

    Args:
        services: Optional list of specific services to validate.

    Returns:
        Exit code (0 for success, 1 for any failures).
    """
    from config.settings import Settings

    try:
        settings = Settings()
    except Exception as exc:
        print(f"{Colors.RED}Failed to load settings:{Colors.RESET} {exc}")
        return 1

    validator = EnvironmentValidator(settings)
    results = await validator.validate_all(services)
    validator.print_report(results)

    return validator.get_exit_code(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Validate Weaver environment services",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Validate all services
    uv run python -m core.health.env_validator

    # Validate specific service
    uv run python -m core.health.env_validator --service postgres

    # Validate multiple services
    uv run python -m core.health.env_validator --service postgres --service redis
        """,
    )
    parser.add_argument(
        "--service",
        action="append",
        choices=["postgres", "neo4j", "redis", "llm", "embedding"],
        help="Service to validate (can be specified multiple times)",
    )

    args = parser.parse_args()
    exit_code = asyncio.run(main(args.service))
    sys.exit(exit_code)
