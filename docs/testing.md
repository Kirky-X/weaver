# Test Quality Guide

This document describes the testing infrastructure, quality standards, and best practices for the Weaver project.

## Test Categories

### Unit Tests (`tests/unit/`)
- **Purpose**: Test individual functions and classes in isolation
- **Characteristics**: Fast, isolated, use mocks for external dependencies
- **Target Coverage**: 80%+ for critical modules
- **Execution Time**: < 60 seconds total

### Integration Tests (`tests/integration/`)
- **Purpose**: Test interactions between components
- **Characteristics**: Use real database connections, test multi-component workflows
- **Requires**: PostgreSQL, Neo4j, Redis (via environment variables)
- **Execution Time**: < 5 minutes total

### E2E Tests (`tests/e2e/`)
- **Purpose**: Test complete user workflows through HTTP API
- **Characteristics**: Use Docker-based isolated environment
- **Requires**: Docker Compose services
- **Execution Time**: < 10 minutes total

### Performance Tests (`tests/performance/`)
- **Purpose**: Benchmark performance-critical operations
- **Characteristics**: Test HNSW index performance, bulk operations
- **Marked**: `@pytest.mark.performance` and `@pytest.mark.slow`

## Running Tests

### Quick Commands

```bash
# Run all unit tests with coverage
uv run pytest --cov=src

# Run only unit tests (fast)
uv run pytest tests/unit/ -v

# Run only integration tests
uv run pytest tests/integration/ -v

# Run E2E tests (requires Docker)
uv run pytest tests/e2e/ -v

# Skip slow tests
uv run pytest -m "not slow"

# Run with parallel execution
uv run pytest tests/unit/ -n auto
```

### CI/CD Commands

```bash
# Full test suite with coverage
uv run pytest --cov=src --cov-report=xml --cov-report=html --junit-xml=test-results.xml

# Performance tests only
uv run pytest tests/performance/ -m performance
```

## Test Quality Metrics

### Coverage Requirements
- **Overall Target**: 80% line coverage
- **Critical Modules**: 90%+ (Pipeline, API endpoints)
- **Measured**: Via `pytest-cov`

### Performance Standards
- Unit tests: < 60s total
- Integration tests: < 5min total
- E2E tests: < 10min total

### Flaky Test Prevention
- Use explicit waits instead of arbitrary sleeps
- Mock time-dependent operations
- Isolate tests from external services
- Clean up state between tests

## Test Fixtures

### Available Fixtures (`tests/conftest.py`)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `event_loop` | session | Event loop for async tests |
| `mock_redis` | function | Mock Redis client |
| `mock_postgres_pool` | function | Mock PostgreSQL pool |
| `mock_neo4j_pool` | function | Mock Neo4j pool |
| `mock_llm_client` | function | Mock LLM client |
| `mock_settings` | function | Mock settings object |
| `sample_article` | function | Sample article data |
| `sample_source_config` | function | Sample source config |

### Test Data Factories (`tests/factories.py`)

```python
from tests.factories import (
    ArticleRawFactory,
    SourceConfigFactory,
    NewsItemFactory,
    PipelineStateFactory,
)

# Create single object
article = ArticleRawFactory.create()

# Create batch
articles = ArticleRawFactory.create_batch(10)

# Create with custom fields
source = SourceConfigFactory.create(name="Custom Source")
```

## Writing Tests

### Unit Test Template

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_feature_works(client, mock_external):
    """Test that feature X works correctly."""
    # Arrange
    mock_external.method.return_value = expected_value

    # Act
    result = await module.function(input_data)

    # Assert
    assert result == expected_value
    mock_external.method.assert_called_once_with(expected_args)
```

### Integration Test Template

```python
import pytest

@pytest.mark.integration
async def test_pipeline_processes_article(postgres_pool, redis_client):
    """Test that pipeline processes an article end-to-end."""
    # Setup test data
    article = await create_test_article(postgres_pool)

    # Execute
    result = await pipeline.process(article)

    # Verify
    assert result.status == "completed"
    assert result.output is not None
```

## Troubleshooting

### Tests Hanging
- Add timeout: `@pytest.mark.timeout(30)`
- Check for unclosed connections
- Verify async cleanup in fixtures

### Flaky Database Tests
- Use transactions and rollback
- Clean tables in `setup` not teardown
- Use unique IDs for test isolation

### Coverage Not Increasing
- Check for unreachable code
- Verify mock targets are correct
- Add branch coverage checks

## CI/CD Integration

### GitHub Actions
- Unit tests run on every PR
- E2E tests run after unit tests pass
- Coverage reports uploaded to Codecov
- JUnit XML reports for test history

### Coverage Thresholds
- PRs must maintain 80%+ coverage
- Coverage drops trigger CI failure
- Exceptions require explicit annotation
