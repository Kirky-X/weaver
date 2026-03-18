# E2E Tests for Weaver

This directory contains end-to-end tests that exercise the complete application stack through the HTTP API.

## Overview

E2E tests validate that the entire system works correctly, from HTTP requests through the API layer, services, and databases.

## Requirements

- Docker and Docker Compose
- Python 3.12+
- All application dependencies installed

## Test Environment

E2E tests use dedicated Docker services (separate from development) to ensure isolation:

| Service | Port | Image |
|---------|------|-------|
| PostgreSQL | 5433 | pgvector/pgvector:pg16 |
| Neo4j | 7475, 7688 | neo4j:5.25 |
| Redis | 6380 | redis:7-alpine |

## Running E2E Tests

### Local Development

```bash
# Start E2E test services
docker compose -f tests/e2e/docker-compose.yml up -d

# Wait for services to be healthy
docker compose -f tests/e2e/docker-compose.yml ps

# Run E2E tests
pytest tests/e2e/ -v

# Stop E2E test services
docker compose -f tests/e2e/docker-compose.yml down -v
```

### In CI/CD

E2E tests run automatically in GitHub Actions with pre-configured service containers.

## Test Structure

```
tests/e2e/
├── __init__.py
├── conftest.py              # Pytest fixtures for E2E testing
├── docker-compose.yml       # Isolated test environment
├── test_env.env            # Environment variables
├── README.md               # This file
├── base/
│   ├── __init__.py
│   └── client.py           # E2EClient wrapper
├── test_health.py         # Health endpoint tests
├── test_sources.py         # Source CRUD tests
├── test_pipeline.py        # Pipeline trigger tests
├── test_articles.py        # Article endpoint tests
└── test_workflows.py       # Cross-cutting workflow tests
```

## Fixtures

| Fixture | Scope | Description |
|---------|-------|-------------|
| `docker_compose` | session | Starts/stops Docker services |
| `db_migrations` | session | Runs Alembic migrations |
| `clean_tables` | function | Truncates tables between tests |
| `e2e_app` | session | Creates FastAPI app |
| `client` | session | TestClient for API calls |
| `auth_headers` | function | Authentication headers |
| `unique_id` | function | Unique ID for test isolation |

## Markers

- `@pytest.mark.e2e` - Marks a test as an E2E test
- E2E tests are excluded from the default test run (use `-m e2e` to include)

## Notes

- Each test function gets a fresh database state via `clean_tables` fixture
- Docker services are started once per test session (not per test)
- Tests use the `TestClient` from FastAPI for synchronous API testing
- API key is loaded from `test_env.env`
