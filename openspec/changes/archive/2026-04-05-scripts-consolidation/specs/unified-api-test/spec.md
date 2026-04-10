## ADDED Requirements

### Requirement: Support E2E and audit subcommands

The script SHALL support `e2e` and `audit` subcommands to run end-to-end tests and API endpoint audits respectively.

#### Scenario: E2E test execution
- **WHEN** user runs `scripts/test_api.py e2e --mode 36kr --max-items 5`
- **THEN** script starts app (unless `--no-start`), registers sources, triggers pipeline, polls tasks, and verifies database results

#### Scenario: API audit execution
- **WHEN** user runs `scripts/test_api.py audit --port 8001`
- **THEN** script tests all API endpoints and logs results to `http_audit.log` and `http_requests.jsonl`

### Requirement: Support multiple source modes in E2E

The E2E subcommand SHALL support `--mode` parameter with values `36kr`, `rss`, and `all` to test different sources.

#### Scenario: 36kr mode E2E test
- **WHEN** user runs `scripts/test_api.py e2e --mode 36kr`
- **THEN** only 36kr source is tested

#### Scenario: RSS mode E2E test
- **WHEN** user runs `scripts/test_api.py e2e --mode rss`
- **THEN** RSS sources (cnbeta, huxiu) are tested

#### Scenario: All mode E2E test
- **WHEN** user runs `scripts/test_api.py e2e --mode all`
- **THEN** both 36kr and RSS sources are tested

### Requirement: Support server start control

The E2E subcommand SHALL support `--no-start` flag to skip app startup when server is already running.

#### Scenario: Skip app startup
- **WHEN** user runs `scripts/test_api.py e2e --no-start`
- **THEN** script connects to existing server without starting new process

### Requirement: Support article limit in E2E

The E2E subcommand SHALL support `--max-items` parameter to limit articles per source.

#### Scenario: Limit E2E articles
- **WHEN** user runs `scripts/test_api.py e2e --max-items 3`
- **THEN** each source processes maximum 3 articles

### Requirement: Support API key configuration

The script SHALL support `--api-key` parameter and `WEAVER_API_KEY` environment variable for authentication.

#### Scenario: Custom API key
- **WHEN** user runs `scripts/test_api.py --api-key custom_key_123`
- **THEN** custom API key is used for authentication headers