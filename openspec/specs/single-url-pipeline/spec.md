## ADDED Requirements

### Requirement: API endpoint for single URL processing

The system SHALL provide a `POST /pipeline/url` endpoint that accepts a single URL and triggers asynchronous pipeline processing.

#### Scenario: Successful URL submission
- **WHEN** user submits a valid URL with correct API key
- **THEN** system returns task_id with status "queued" and queued_at timestamp

#### Scenario: Missing API key
- **WHEN** request is sent without X-API-Key header
- **THEN** system returns 401 error with message "Missing API key"

#### Scenario: Invalid API key
- **WHEN** request is sent with incorrect API key
- **THEN** system returns 403 error with message "Invalid API Key"

### Requirement: URL validation with SSRF protection

The system SHALL validate submitted URLs to prevent Server-Side Request Forgery attacks.

#### Scenario: SSRF blocked - localhost
- **WHEN** URL contains localhost, 127.0.0.1, or 0.0.0.0
- **THEN** system returns 403 error with message about SSRF risk

#### Scenario: SSRF blocked - private IP
- **WHEN** URL resolves to private IP range (10.x.x.x, 172.16-31.x.x, 192.168.x.x)
- **THEN** system returns 403 error with message about SSRF risk

#### Scenario: SSRF blocked - cloud metadata
- **WHEN** URL points to 169.254.169.254
- **THEN** system returns 403 error with message about SSRF risk

#### Scenario: Invalid URL format
- **WHEN** URL is malformed or not http/https protocol
- **THEN** system returns 400 error with message about invalid URL

### Requirement: Optional whitelist domain validation

The system SHALL support optional whitelist mode that restricts processing to configured domains.

#### Scenario: Whitelist mode enabled - allowed domain
- **WHEN** whitelist_mode is true and URL domain is in allowed_domains list
- **THEN** system accepts and processes the URL

#### Scenario: Whitelist mode enabled - blocked domain
- **WHEN** whitelist_mode is true and URL domain is NOT in allowed_domains list
- **THEN** system returns 403 error with message about domain not allowed

#### Scenario: Whitelist mode disabled
- **WHEN** whitelist_mode is false
- **THEN** system accepts any valid URL (after SSRF check)

### Requirement: Asynchronous pipeline processing

The system SHALL process submitted URLs asynchronously through the full pipeline.

#### Scenario: Processing flow
- **WHEN** URL is accepted
- **THEN** system SHALL:
  1. Create task with unique task_id
  2. Store initial status "queued" in Redis
  3. Return task_id immediately
  4. Execute crawl → clean → categorize → vectorize → analyze → credibility check → entity extraction → persist in background

#### Scenario: Task status query compatibility
- **WHEN** user queries `GET /pipeline/tasks/{task_id}` with task_id from this endpoint
- **THEN** system returns same status format as batch pipeline tasks

### Requirement: Task status tracking

The system SHALL track and update task status throughout the processing lifecycle.

#### Scenario: Status progression on success
- **WHEN** URL processing completes successfully
- **THEN** task status transitions: queued → running → completed

#### Scenario: Status progression on failure
- **WHEN** URL processing fails at any stage
- **THEN** task status is "failed" with error message in Redis

#### Scenario: Progress statistics included
- **WHEN** task status is queried
- **THEN** response includes total_processed, completed_count, failed_count statistics