# Spec: API Test Coverage

## ADDED Requirements

### Requirement: Search API endpoints SHALL have unit test coverage

The `/api/v1/search/*` endpoints SHALL be tested for:
- Successful search queries
- Invalid parameter handling
- Authentication/authorization

#### Scenario: Successful vector search
- **WHEN** GET `/api/v1/search/vector?q=test&limit=10` is called with valid auth
- **THEN** response SHALL be 200 with search results

#### Scenario: Invalid limit parameter
- **WHEN** GET `/api/v1/search/vector?q=test&limit=abc` is called
- **THEN** response SHALL be 422 with validation error

### Requirement: Graph metrics API endpoints SHALL have unit test coverage

The `/api/v1/graph/metrics/*` endpoints SHALL be tested for:
- Metrics retrieval
- Empty graph handling
- Cache behavior

#### Scenario: Successful metrics retrieval
- **WHEN** GET `/api/v1/graph/metrics/overview` is called with valid auth
- **THEN** response SHALL be 200 with metrics data

### Requirement: Admin LLM API endpoints SHALL have unit test coverage

The `/api/v1/admin/llm/*` endpoints SHALL be tested for:
- Usage statistics retrieval
- Hourly aggregation queries
- Admin authorization

#### Scenario: Unauthorized access blocked
- **WHEN** GET `/api/v1/admin/llm/usage` is called without admin role
- **THEN** response SHALL be 403 Forbidden

### Requirement: Communities API endpoints SHALL have unit test coverage

The `/api/v1/communities/*` endpoints SHALL be tested for:
- Community listing
- Community detail retrieval
- Graph endpoint integration

#### Scenario: Community list pagination
- **WHEN** GET `/api/v1/communities?offset=0&limit=10` is called
- **THEN** response SHALL be 200 with paginated community list

### Requirement: Graph relations API endpoints SHALL have unit test coverage

The `/api/v1/graph/relations/*` endpoints SHALL be tested for:
- Relation queries
- Filtering by entity
- Pagination

#### Scenario: Relations by entity
- **WHEN** GET `/api/v1/graph/relations?entity_id=123` is called
- **THEN** response SHALL be 200 with relations involving entity 123

### Requirement: API integration tests SHALL cover cross-endpoint workflows

Integration tests SHALL verify:
- Health check integration
- LLM usage pipeline
- Vector repository operations

#### Scenario: Health check with all services
- **WHEN** GET `/api/v1/health` is called
- **THEN** response SHALL include status of postgres, redis, neo4j

### Requirement: E2E tests SHALL cover core user flows

E2E tests SHALL cover:
- Article processing pipeline
- Search and retrieval flow
- Graph exploration flow

#### Scenario: Single URL processing
- **WHEN** POST `/api/v1/pipeline/url` with valid URL is called
- **THEN** article SHALL be processed and entities extracted