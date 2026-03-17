#!/bin/bash
set -e

echo "Starting weaver services..."

# Wait for PostgreSQL
echo "Waiting for PostgreSQL..."
until PGPASSWORD=postgres psql -h postgres -U postgres -c '\q' 2>/dev/null; do
  echo "PostgreSQL is unavailable - sleeping"
  sleep 2
done
echo "PostgreSQL is up"

# Wait for Neo4j
echo "Waiting for Neo4j..."
until curl -s http://localhost:7474 >/dev/null 2>&1; do
  echo "Neo4j is unavailable - sleeping"
  sleep 2
done
echo "Neo4j is up"

# Run Alembic migrations
echo "Running database migrations..."
cd /app
uv run alembic upgrade head

# Create Neo4j constraints
echo "Creating Neo4j constraints..."
uv run python -c "
import asyncio
from core.db.neo4j import Neo4jPool

async def setup_neo4j():
    pool = Neo4jPool('bolt://neo4j:7687', ('neo4j', 'neo4j123'))
    await pool.startup()

    # Create constraints
    queries = [
        '''CREATE CONSTRAINT entity_name_type_unique IF NOT EXISTS
           FOR (e:Entity) REQUIRE (e.canonical_name, e.type) IS UNIQUE'''
    ]

    for q in queries:
        try:
            await pool.execute_query(q)
            print(f'Created constraint')
        except Exception as e:
            print(f'Constraint creation: {e}')

    await pool.shutdown()

asyncio.run(setup_neo4j())
"

echo "Setup complete!"

# Start the application
exec "$@"
