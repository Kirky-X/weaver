## MODIFIED Requirements

### Requirement: HTTP API-Only Pipeline Testing

The unified pipeline test script SHALL execute all pipeline operations through HTTP API endpoints, ensuring API testing consistency and completeness.

#### Scenario: Create source via API
- **WHEN** the script creates a data source
- **THEN** it SHALL call `POST /api/v1/sources` with the source configuration
- **AND** it SHALL handle 201 (created) or 409 (already exists) responses

#### Scenario: Trigger pipeline via API
- **WHEN** the script starts a pipeline run
- **THEN** it SHALL call `POST /api/v1/pipeline/trigger` with source_id and max_items
- **AND** it SHALL receive a task_id for monitoring

#### Scenario: Monitor task via API
- **WHEN** the script monitors pipeline progress
- **THEN** it SHALL poll `GET /api/v1/pipeline/tasks/{task_id}` at regular intervals
- **AND** it SHALL report status, processed count, and completion

#### Scenario: Verify results via API
- **WHEN** the script verifies data storage
- **THEN** it SHALL call `GET /api/v1/articles` to count stored articles
- **AND** it MAY call `GET /api/v1/graph/entities/{name}` for entity verification

### Requirement: Support Multiple Test Modes

The script SHALL support `--mode` parameter with values `newsnow`, `rss`, and `strategy`.

#### Scenario: NewsNow mode
- **WHEN** user runs `scripts/test_pipeline_api_unified.py --mode newsnow --source-id 36kr --max-items 5`
- **THEN** script creates a NewsNow source with URL `https://www.newsnow.world/api/s?id=36kr`
- **AND** triggers pipeline and verifies storage via API

#### Scenario: RSS mode
- **WHEN** user runs `scripts/test_pipeline_api_unified.py --mode rss --source solidot --max-items 2`
- **THEN** script creates an RSS source with URL `https://www.solidot.org/index.rss`
- **AND** triggers pipeline and verifies storage via API

#### Scenario: Strategy mode
- **WHEN** user runs `scripts/test_pipeline_api_unified.py --mode strategy`
- **THEN** script sets environment variables to force database failover
- **AND** verifies that DuckDB and LadybugDB are used instead of PostgreSQL and Neo4j

### Requirement: Database Cleanup Support

The script SHALL support `--clear-db` parameter with direct database access for cleanup operations.

#### Scenario: Clear databases before test
- **WHEN** user runs `scripts/test_pipeline_api_unified.py --clear-db`
- **THEN** script SHALL delete all test data from DuckDB/PostgreSQL tables
- **AND** script SHALL delete all nodes from LadybugDB/Neo4j
- **NOTE** This operation bypasses API due to lack of cleanup endpoints

### Requirement: Server Management

The script SHALL start and manage the FastAPI server for testing.

#### Scenario: Start API server
- **WHEN** the script begins execution
- **THEN** it SHALL start the FastAPI server on the specified port (default 8000)
- **AND** it SHALL wait for the server to be ready before making API calls

#### Scenario: Graceful shutdown
- **WHEN** the script completes or encounters an error
- **THEN** it SHALL shut down the API server gracefully
- **AND** it SHALL close all database connections

### Requirement: Error Handling

The script SHALL provide clear error messages and appropriate exit codes.

#### Scenario: API timeout
- **WHEN** an API call exceeds the timeout period (default 300s)
- **THEN** script SHALL report timeout error with task_id
- **AND** script SHALL exit with code 1

#### Scenario: Verification failure
- **WHEN** verification finds no stored articles
- **THEN** script SHALL report verification failure
- **AND** script SHALL exit with code 1

#### Scenario: Strategy mode failure
- **WHEN** strategy mode does not use fallback databases
- **THEN** script SHALL report database type mismatch
- **AND** script SHALL exit with code 1

## Command Line Interface

```
usage: test_pipeline_api_unified.py [-h] [--mode {newsnow,rss,strategy}]
                                     [--source SOURCE] [--source-id SOURCE_ID]
                                     [--max-items MAX_ITEMS] [--clear-db]
                                     [--timeout TIMEOUT] [--port PORT]

Unified pipeline test script via HTTP API.
No backward compatibility with old scripts.

arguments:
  --mode {newsnow,rss,strategy}
                        Test mode (default: newsnow)
  --source SOURCE       RSS source name for rss mode (default: solidot)
  --source-id SOURCE_ID
                        NewsNow source ID for newsnow mode (default: 36kr)
  --max-items MAX_ITEMS
                        Maximum items to process (default: 5)
  --clear-db            Clear databases before testing
  --timeout TIMEOUT     Pipeline timeout in seconds (default: 300)
  --port PORT           API server port (default: 8000)

Examples:
  # NewsNow mode (default)
  uv run scripts/test_pipeline_api_unified.py --mode newsnow --max-items 5

  # RSS mode
  uv run scripts/test_pipeline_api_unified.py --mode rss --source solidot --max-items 2

  # Strategy mode (test database failover)
  uv run scripts/test_pipeline_api_unified.py --mode strategy

  # With database cleanup
  uv run scripts/test_pipeline_api_unified.py --clear-db --max-items 3
```