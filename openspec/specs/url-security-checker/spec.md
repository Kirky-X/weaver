## ADDED Requirements

### Requirement: URL security validation pipeline
The system SHALL validate URLs through a multi-layer security pipeline including SSRF protection, malicious URL detection, and SSL certificate verification.

#### Scenario: Safe URL passes all checks
- **WHEN** a URL is submitted for validation
- **AND** the URL passes SSRF, URLhaus, PhishTank, heuristic, and SSL checks
- **THEN** the system returns SAFE risk level with is_safe=true

#### Scenario: Malicious URL is blocked
- **WHEN** a URL is found in URLhaus or PhishTank databases
- **THEN** the system returns BLOCKED risk level with is_safe=false
- **AND** the check result includes the threat source

#### Scenario: Cache hit returns cached result
- **WHEN** a URL validation result exists in cache
- **THEN** the system returns cached result without executing checks
- **AND** the result is marked as cached=true

### Requirement: API-first with local fallback
The system SHALL prioritize URLhaus API when configured, and fall back to local checks when API fails.

#### Scenario: URLhaus API returns malicious
- **WHEN** URLhaus API key is configured
- **AND** API returns malicious status for the URL
- **THEN** the system returns BLOCKED risk level
- **AND** skips subsequent local checks

#### Scenario: URLhaus API returns safe
- **WHEN** URLhaus API key is configured
- **AND** API returns safe status for the URL
- **THEN** the system skips PhishTank and heuristic checks
- **AND** still performs SSL verification

#### Scenario: URLhaus API fails with fallback
- **WHEN** URLhaus API key is configured
- **AND** API request fails (timeout, rate limit, auth error)
- **THEN** the system falls back to local checks
- **AND** logs the API failure reason

### Requirement: Differential caching
The system SHALL cache validation results with different TTL based on risk level.

#### Scenario: Safe result cached for 6 hours
- **WHEN** a URL is validated as SAFE
- **THEN** the result is cached for 21600 seconds (6 hours)

#### Scenario: Malicious result cached for 15 minutes
- **WHEN** a URL is validated as HIGH or BLOCKED
- **THEN** the result is cached for 900 seconds (15 minutes)

### Requirement: Risk level classification
The system SHALL classify URLs into risk levels: SAFE, LOW, MEDIUM, HIGH, BLOCKED.

#### Scenario: Risk aggregation from multiple checks
- **WHEN** multiple checks return different risk levels
- **THEN** the system returns the highest risk level among all checks

#### Scenario: SAFE and LOW are considered safe
- **WHEN** final risk level is SAFE or LOW
- **THEN** is_safe returns true

#### Scenario: MEDIUM, HIGH, BLOCKED are considered unsafe
- **WHEN** final risk level is MEDIUM, HIGH, or BLOCKED
- **THEN** is_safe returns false