#!/usr/bin/env python3
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Environment validation script for Weaver.

Validates all infrastructure services (PostgreSQL, Neo4j, Redis) and
AI services (LLM providers, embedding models) before running tests.

Usage:
    uv run scripts/validate_environment.py [--service SERVICE]

Examples:
    # Validate all services
    uv run scripts/validate_environment.py

    # Validate specific service
    uv run scripts/validate_environment.py --service postgres

    # Validate multiple services
    uv run scripts/validate_environment.py --service postgres --service redis
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

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
    details: list[str]
    suggestions: list[str]


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
            # Expired
            del self._cache[key]
            return None

        return result

    def set(self, key: str, result: ValidationResult) -> None:
        """Cache a validation result."""
        self._cache[key] = (result, datetime.now())


# Global cache instance
_validation_cache = ValidationCache(ttl_minutes=5)


# ────────────────────────────────────────────────────────────
# Helper Functions
# ────────────────────────────────────────────────────────────


def print_header(title: str) -> None:
    """Print section header."""
    width = 60
    print(f"\n{Colors.BOLD}{title}{Colors.RESET}")
    print("═" * width)


def print_result(result: ValidationResult) -> None:
    """Print validation result with colored indicators."""
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


# ────────────────────────────────────────────────────────────
# Validator Functions
# ────────────────────────────────────────────────────────────


async def validate_postgres(settings: Any) -> ValidationResult:
    """Validate PostgreSQL connectivity and pgvector extension.

    Args:
        settings: Application settings.

    Returns:
        ValidationResult with status and details.
    """
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    dsn = settings.postgres.dsn
    details = []
    suggestions = []

    # Retry logic for network resilience
    max_retries = 3
    retry_delay = 2.0

    for attempt in range(max_retries):
        try:
            # Create temporary engine
            engine = create_async_engine(dsn, echo=False)

            # Test connection
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                result.fetchone()

            details.append("✓ Connection successful")

            # Extract database name from DSN for display
            db_name = dsn.split("/")[-1].split("?")[0]
            details.append(f"✓ Database: {db_name}")

            # Check pgvector extension
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT * FROM pg_extension WHERE extname = 'vector'")
                )
                extension = result.fetchone()

                if extension:
                    details.append("✓ pgvector extension available")
                else:
                    details.append("✗ pgvector extension not installed")
                    suggestions.append("Run: CREATE EXTENSION IF NOT EXISTS vector; in PostgreSQL")

            # Close engine
            await engine.dispose()

            # Success - return healthy result
            return ValidationResult(
                service="PostgreSQL",
                healthy=len(suggestions) == 0,
                details=details,
                suggestions=suggestions,
            )

        except Exception as exc:
            if attempt < max_retries - 1:
                # Retry after delay
                await asyncio.sleep(retry_delay)
                continue
            else:
                # Final attempt failed
                error_msg = str(exc)
                details.append(f"✗ Connection failed: {error_msg}")

                # Provide specific suggestions based on error
                if "Connection refused" in error_msg:
                    suggestions.append(f"Check if PostgreSQL is running on the configured host")
                elif "authentication failed" in error_msg.lower():
                    suggestions.append("Check PostgreSQL credentials in settings")
                elif "database" in error_msg.lower() and "does not exist" in error_msg.lower():
                    suggestions.append("Create the database or check database name")
                else:
                    suggestions.append("Check PostgreSQL service status and connection parameters")

                return ValidationResult(
                    service="PostgreSQL",
                    healthy=False,
                    details=details,
                    suggestions=suggestions,
                )


async def validate_neo4j(settings: Any) -> ValidationResult:
    """Validate Neo4j connectivity.

    Args:
        settings: Application settings.

    Returns:
        ValidationResult with status and details.
    """
    import asyncio

    from neo4j import AsyncGraphDatabase

    uri = settings.neo4j.uri
    user = settings.neo4j.user
    password = settings.neo4j.password

    details = []
    suggestions = []

    # Retry logic for network resilience
    max_retries = 3
    retry_delay = 2.0

    for attempt in range(max_retries):
        try:
            # Create temporary driver
            driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

            # Verify connectivity
            await driver.verify_connectivity()
            details.append("✓ Connection successful")
            details.append(f"✓ URI: {uri}")

            # Close driver
            await driver.close()

            # Success
            return ValidationResult(
                service="Neo4j",
                healthy=True,
                details=details,
                suggestions=suggestions,
            )

        except Exception as exc:
            if attempt < max_retries - 1:
                # Retry after delay
                await asyncio.sleep(retry_delay)
                continue
            else:
                # Final attempt failed
                error_msg = str(exc)
                details.append(f"✗ Connection failed: {error_msg}")

                # Provide specific suggestions based on error
                if "Connection refused" in error_msg or "Failed to resolve address" in error_msg:
                    suggestions.append(f"Check if Neo4j is running at {uri}")
                elif (
                    "authentication failed" in error_msg.lower()
                    or "unauthorized" in error_msg.lower()
                ):
                    suggestions.append("Check Neo4j credentials (user/password) in settings")
                elif "ServiceUnavailable" in error_msg:
                    suggestions.append(
                        "Neo4j service is unavailable. Check if the database is fully started"
                    )
                else:
                    suggestions.append("Check Neo4j service status and connection parameters")

                return ValidationResult(
                    service="Neo4j",
                    healthy=False,
                    details=details,
                    suggestions=suggestions,
                )


async def validate_redis(settings: Any) -> ValidationResult:
    """Validate Redis connectivity.

    Args:
        settings: Application settings.

    Returns:
        ValidationResult with status and details.
    """
    import asyncio

    from redis.asyncio import ConnectionPool, Redis

    url = settings.redis.url
    details = []
    suggestions = []

    # Retry logic for network resilience
    max_retries = 3
    retry_delay = 2.0

    for attempt in range(max_retries):
        try:
            # Create temporary connection pool
            pool = ConnectionPool.from_url(
                url,
                decode_responses=True,
                max_connections=10,
            )
            redis_client = Redis(connection_pool=pool)

            # Test connection with ping
            await redis_client.ping()
            details.append("✓ Connection successful")

            # Extract database number from URL
            db_num = url.split("/")[-1] if "/" in url else "0"
            details.append(f"✓ Database: {db_num}")

            # Close connection
            await redis_client.aclose()
            await pool.disconnect()

            # Success
            return ValidationResult(
                service="Redis",
                healthy=True,
                details=details,
                suggestions=suggestions,
            )

        except Exception as exc:
            if attempt < max_retries - 1:
                # Retry after delay
                await asyncio.sleep(retry_delay)
                continue
            else:
                # Final attempt failed
                error_msg = str(exc)
                details.append(f"✗ Connection failed: {error_msg}")

                # Provide specific suggestions based on error
                if "Connection refused" in error_msg:
                    suggestions.append("Check if Redis is running on the configured host and port")
                elif "authentication" in error_msg.lower():
                    suggestions.append("Check Redis authentication credentials in settings")
                elif "no such file" in error_msg.lower():
                    suggestions.append("Check Redis Unix socket path if using socket connection")
                else:
                    suggestions.append("Check Redis service status and connection URL")

                return ValidationResult(
                    service="Redis",
                    healthy=False,
                    details=details,
                    suggestions=suggestions,
                )


async def validate_llm(settings: Any) -> ValidationResult:
    """Validate LLM provider accessibility.

    Args:
        settings: Application settings.

    Returns:
        ValidationResult with status and details.
    """
    import asyncio

    import httpx

    details = []
    suggestions = []

    # Get configured providers
    providers = settings.llm.providers
    if not providers:
        details.append("✗ No LLM providers configured")
        suggestions.append("Configure at least one LLM provider in settings.toml")
        result = ValidationResult(
            service="LLM",
            healthy=False,
            details=details,
            suggestions=suggestions,
        )

    # Validate primary provider (first in the list)
    primary_provider_name = next(iter(providers.keys()))
    primary_config = providers[primary_provider_name]

    provider_type = primary_config.get("provider", "unknown")
    model = primary_config.get("model", "unknown")
    base_url = primary_config.get("base_url", "")
    api_key = primary_config.get("api_key", "")

    # Check cache
    cache_key = f"llm:{provider_type}:{model}:{base_url}"
    cached_result = _validation_cache.get(cache_key)
    if cached_result:
        return cached_result

    details.append(f"Provider: {provider_type} ({primary_provider_name})")
    details.append(f"Model: {model}")

    # Helper function to cache and return
    def cache_result(result: ValidationResult) -> ValidationResult:
        _validation_cache.set(cache_key, result)
        return result

    # Retry logic for network resilience
    max_retries = 3
    retry_delay = 2.0

    for attempt in range(max_retries):
        try:
            if provider_type == "openai":
                # Validate OpenAI
                if not api_key:
                    details.append("✗ API key not configured")
                    suggestions.append(
                        "Set OpenAI API key in settings.toml or OPENAI_API_KEY environment variable"
                    )
                    return ValidationResult(
                        service="LLM (OpenAI)",
                        healthy=False,
                        details=details,
                        suggestions=suggestions,
                    )

                # Test API connectivity with a simple request
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        f"{base_url}/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )

                    if response.status_code == 200:
                        details.append("✓ API key valid")
                        details.append(f"✓ Provider accessible at {base_url}")

                        # Check if configured model is available
                        models_data = response.json()
                        available_models = [m["id"] for m in models_data.get("data", [])]
                        if model in available_models:
                            details.append(f"✓ Model {model} available")
                        else:
                            details.append(f"⚠ Model {model} not found in available models")

                        return ValidationResult(
                            service="LLM (OpenAI)",
                            healthy=True,
                            details=details,
                            suggestions=suggestions,
                        )
                    else:
                        details.append(f"✗ API returned status {response.status_code}")
                        suggestions.append("Check OpenAI API key and base URL")
                        return ValidationResult(
                            service="LLM (OpenAI)",
                            healthy=False,
                            details=details,
                            suggestions=suggestions,
                        )

            elif provider_type == "ollama":
                # Validate Ollama
                async with httpx.AsyncClient(timeout=10.0) as client:
                    # Check if Ollama server is reachable
                    response = await client.get(f"{base_url}/api/tags")

                    if response.status_code == 200:
                        details.append(f"✓ Provider accessible at {base_url}")

                        # Check if model is available
                        models_data = response.json()
                        available_models = [
                            m.get("name", "") for m in models_data.get("models", [])
                        ]

                        # Ollama model names might have :latest suffix
                        model_variants = [model, f"{model}:latest"]
                        if any(m in available_models for m in model_variants):
                            details.append(f"✓ Model {model} available")
                        else:
                            details.append(f"✗ Model {model} not found")
                            suggestions.append(f"Pull the model with: ollama pull {model}")

                        return ValidationResult(
                            service="LLM (Ollama)",
                            healthy=True,
                            details=details,
                            suggestions=suggestions,
                        )
                    else:
                        details.append(f"✗ Server returned status {response.status_code}")
                        suggestions.append("Check Ollama server status")
                        return ValidationResult(
                            service="LLM (Ollama)",
                            healthy=False,
                            details=details,
                            suggestions=suggestions,
                        )

            elif provider_type == "anthropic":
                # Validate Anthropic/Anthropic-compatible proxy
                # For local proxies, just test connectivity
                async with httpx.AsyncClient(timeout=10.0) as client:
                    try:
                        # Try to connect to the base URL
                        response = await client.get(base_url, follow_redirects=True)

                        # For Anthropic proxies, we just verify the service is running
                        # Actual model validation happens during real API calls
                        details.append(f"✓ Provider accessible at {base_url}")
                        details.append(f"✓ Model {model} configured")

                        return ValidationResult(
                            service="LLM (Anthropic)",
                            healthy=True,
                            details=details,
                            suggestions=suggestions,
                        )
                    except httpx.ConnectError:
                        details.append(f"✗ Cannot connect to {base_url}")
                        suggestions.append("Check if the Anthropic proxy service is running")
                        return ValidationResult(
                            service="LLM (Anthropic)",
                            healthy=False,
                            details=details,
                            suggestions=suggestions,
                        )
            else:
                details.append(f"✗ Unknown provider type: {provider_type}")
                suggestions.append("Configure a supported provider (openai or ollama)")
                return ValidationResult(
                    service="LLM",
                    healthy=False,
                    details=details,
                    suggestions=suggestions,
                )

        except httpx.ConnectError as exc:
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                continue
            else:
                details.append(f"✗ Connection failed: {exc!s}")
                suggestions.append(f"Check if {provider_type} server is running at {base_url}")
                return ValidationResult(
                    service=f"LLM ({provider_type})",
                    healthy=False,
                    details=details,
                    suggestions=suggestions,
                )
        except Exception as exc:
            details.append(f"✗ Validation failed: {exc!s}")
            suggestions.append(f"Check {provider_type} configuration")
            return ValidationResult(
                service=f"LLM ({provider_type})",
                healthy=False,
                details=details,
                suggestions=suggestions,
            )

    # Should not reach here
    return ValidationResult(
        service="LLM",
        healthy=False,
        details=["✗ Validation failed after all retries"],
        suggestions=["Check LLM provider configuration"],
    )


async def validate_embedding(settings: Any) -> ValidationResult:
    """Validate embedding model accessibility.

    Args:
        settings: Application settings.

    Returns:
        ValidationResult with status and details.
    """
    import asyncio

    import httpx

    details = []
    suggestions = []

    # Get embedding provider configuration
    embedding_provider = settings.llm.embedding_provider
    embedding_model = settings.llm.embedding_model

    details.append(f"Provider: {embedding_provider}")
    details.append(f"Model: {embedding_model}")

    # Get provider config
    providers = settings.llm.providers
    if embedding_provider not in providers:
        details.append(f"✗ Provider '{embedding_provider}' not configured")
        suggestions.append(f"Configure '{embedding_provider}' provider in settings.toml")
        return ValidationResult(
            service="Embedding",
            healthy=False,
            details=details,
            suggestions=suggestions,
        )

    provider_config = providers[embedding_provider]
    provider_type = provider_config.get("provider", "unknown")
    base_url = provider_config.get("base_url", "")
    api_key = provider_config.get("api_key", "")

    # Retry logic for network resilience
    max_retries = 3
    retry_delay = 2.0

    for attempt in range(max_retries):
        try:
            if provider_type == "openai":
                # Validate OpenAI embeddings
                if not api_key:
                    details.append("✗ API key not configured")
                    suggestions.append("Set OpenAI API key for embedding provider")
                    return ValidationResult(
                        service="Embedding (OpenAI)",
                        healthy=False,
                        details=details,
                        suggestions=suggestions,
                    )

                # Test embedding API with a simple request
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{base_url}/embeddings",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "input": "test",
                            "model": embedding_model,
                        },
                    )

                    if response.status_code == 200:
                        details.append("✓ API key valid")
                        details.append(f"✓ Provider accessible at {base_url}")
                        details.append(f"✓ Model {embedding_model} available")

                        return ValidationResult(
                            service="Embedding (OpenAI)",
                            healthy=True,
                            details=details,
                            suggestions=suggestions,
                        )
                    else:
                        error_detail = response.text[:200]
                        details.append(f"✗ API returned status {response.status_code}")
                        details.append(f"  Error: {error_detail}")
                        suggestions.append("Check embedding model name and API access")
                        return ValidationResult(
                            service="Embedding (OpenAI)",
                            healthy=False,
                            details=details,
                            suggestions=suggestions,
                        )

            elif provider_type == "ollama":
                # Validate Ollama embeddings
                async with httpx.AsyncClient(timeout=30.0) as client:
                    # Ollama embedding endpoint
                    response = await client.post(
                        f"{base_url}/api/embeddings",
                        json={
                            "model": embedding_model,
                            "prompt": "test",
                        },
                    )

                    if response.status_code == 200:
                        details.append(f"✓ Provider accessible at {base_url}")
                        details.append(f"✓ Model {embedding_model} available")

                        return ValidationResult(
                            service="Embedding (Ollama)",
                            healthy=True,
                            details=details,
                            suggestions=suggestions,
                        )
                    else:
                        details.append(f"✗ Server returned status {response.status_code}")
                        suggestions.append(
                            f"Check if embedding model {embedding_model} is pulled in Ollama"
                        )
                        return ValidationResult(
                            service="Embedding (Ollama)",
                            healthy=False,
                            details=details,
                            suggestions=suggestions,
                        )
            else:
                details.append(f"✗ Unknown provider type: {provider_type}")
                suggestions.append("Configure a supported embedding provider (openai or ollama)")
                return ValidationResult(
                    service="Embedding",
                    healthy=False,
                    details=details,
                    suggestions=suggestions,
                )

        except httpx.ConnectError as exc:
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                continue
            else:
                details.append(f"✗ Connection failed: {exc!s}")
                suggestions.append(f"Check if {provider_type} server is running at {base_url}")
                return ValidationResult(
                    service=f"Embedding ({provider_type})",
                    healthy=False,
                    details=details,
                    suggestions=suggestions,
                )
        except Exception as exc:
            details.append(f"✗ Validation failed: {exc!s}")
            suggestions.append(f"Check {provider_type} embedding configuration")
            return ValidationResult(
                service=f"Embedding ({provider_type})",
                healthy=False,
                details=details,
                suggestions=suggestions,
            )

    # Should not reach here
    return ValidationResult(
        service="Embedding",
        healthy=False,
        details=["✗ Validation failed after all retries"],
        suggestions=["Check embedding provider configuration"],
    )


# ────────────────────────────────────────────────────────────
# Main Function
# ────────────────────────────────────────────────────────────


async def main(services: list[str] | None = None) -> int:
    """Run environment validation.

    Args:
        services: Optional list of specific services to validate.
                 If None, validates all services.

    Returns:
        Exit code (0 for all healthy, 1 for any failures).
    """
    # Load settings
    try:
        import sys
        from pathlib import Path

        # Add src directory to Python path
        src_path = Path(__file__).resolve().parent.parent / "src"
        if str(src_path) not in sys.path:
            sys.path.insert(0, str(src_path))

        from config.settings import Settings

        settings = Settings()
    except Exception as exc:
        print(f"{Colors.RED}Failed to load settings:{Colors.RESET} {exc}")
        return 1

    # Define all validators
    all_validators = {
        "postgres": validate_postgres,
        "neo4j": validate_neo4j,
        "redis": validate_redis,
        "llm": validate_llm,
        "embedding": validate_embedding,
    }

    # Select validators to run
    if services:
        validators = {k: v for k, v in all_validators.items() if k in services}
        if not validators:
            print(f"{Colors.RED}No valid services specified.{Colors.RESET}")
            print(f"Available services: {', '.join(all_validators.keys())}")
            return 1
    else:
        validators = all_validators

    # Run validations
    print_header("Environment Validation Report")

    results = []
    for validator in validators.values():
        result = await validator(settings)
        results.append(result)
        print_result(result)

    # Print summary
    healthy_count = sum(1 for r in results if r.healthy)
    total_count = len(results)

    print_header("Summary")
    if healthy_count == total_count:
        print(f"{Colors.GREEN}All {total_count} services healthy{Colors.RESET}")
        return 0
    else:
        print(f"{Colors.YELLOW}{healthy_count}/{total_count} services healthy{Colors.RESET}")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Validate Weaver environment services",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Validate all services
    uv run scripts/validate_environment.py

    # Validate specific service
    uv run scripts/validate_environment.py --service postgres

    # Validate multiple services
    uv run scripts/validate_environment.py --service postgres --service redis
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
