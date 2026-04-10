## ADDED Requirements

### Requirement: URLhaus API integration
The system SHALL integrate with URLhaus API for real-time malicious URL lookup.

#### Scenario: Malicious URL found
- **WHEN** URLhaus API returns query_status="ok"
- **THEN** the client returns MALICIOUS status
- **AND** includes threat type in response

#### Scenario: Safe URL not found
- **WHEN** URLhaus API returns query_status="no_results"
- **THEN** the client returns SAFE status

#### Scenario: Invalid API key
- **WHEN** URLhaus API returns query_status="invalid_api_key"
- **THEN** the client returns ERROR status
- **AND** includes should_fallback=true for local check fallback

### Requirement: Error handling with fallback
The system SHALL handle API errors gracefully and indicate when fallback is needed.

#### Scenario: Rate limit exceeded
- **WHEN** URLhaus API returns HTTP 429
- **THEN** the client returns ERROR status with "Rate limited" message
- **AND** includes should_fallback=true

#### Scenario: Network timeout
- **WHEN** URLhaus API request times out
- **THEN** the client returns ERROR status with "Request timeout" message
- **AND** includes should_fallback=true

#### Scenario: HTTP error
- **WHEN** URLhaus API returns non-200 status code
- **THEN** the client returns ERROR status with HTTP status message
- **AND** includes should_fallback=true

### Requirement: Configuration
The system SHALL support URLhaus API configuration via settings.

#### Scenario: API key not configured
- **WHEN** urlhaus_api_key is empty
- **THEN** the client returns ERROR status with "API key not configured" message

#### Scenario: Custom timeout
- **WHEN** urlhaus_api_timeout is configured
- **THEN** HTTP requests use the configured timeout value