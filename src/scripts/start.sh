#!/bin/bash
# Copyright (c) 2026 KirkyX. All Rights Reserved
set -e

echo "Starting weaver services..."

# Run Python-based environment validation
echo "Running pre-startup environment validation..."
cd /app
uv run python -c "
import asyncio
import sys
from config.settings import Settings
from core.health.env_validator import EnvironmentValidator

async def validate():
    settings = Settings()
    validator = EnvironmentValidator(settings)

    # Validate infrastructure services only (postgres, redis, neo4j)
    results = await validator.validate_all(['postgres', 'redis', 'neo4j'])
    validator.print_report(results)

    # Check required services
    required = settings.health_check.required_services
    for service in required:
        if service in results and not results[service].healthy:
            print(f'ERROR: Required service {service} is not available!')
            sys.exit(1)

    # Neo4j is optional - just warn if unavailable
    neo4j_result = results.get('neo4j')
    if neo4j_result and not neo4j_result.healthy:
        print('WARNING: Neo4j is not available. Some features will be disabled.')

    print('Environment validation passed!')
    return 0

sys.exit(asyncio.run(validate()))
"

# Run Alembic migrations
echo "Running database migrations..."
uv run alembic upgrade head

# Initialize Neo4j constraints (if Neo4j is available)
echo "Initializing Neo4j constraints..."
uv run python -c "
import asyncio
from config.settings import Settings
from core.db import Neo4jPool, initialize_neo4j

async def setup_neo4j():
    try:
        settings = Settings()
        pool = Neo4jPool(
            settings.neo4j.uri,
            (settings.neo4j.user, settings.neo4j.password)
        )
        await pool.startup()

        # Initialize constraints
        result = await initialize_neo4j(pool)
        if result.get('constraints_created'):
            print(f\"Created constraints: {result['constraints_created']}\")
        else:
            print('All Neo4j constraints already exist.')

        await pool.shutdown()
    except Exception as e:
        print(f'Neo4j initialization skipped: {e}')
        # Neo4j is optional, so we don't fail

asyncio.run(setup_neo4j())
"

echo "Setup complete!"

# Start the application
exec "$@"