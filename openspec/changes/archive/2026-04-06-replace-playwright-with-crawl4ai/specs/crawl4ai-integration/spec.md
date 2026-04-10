## ADDED Requirements

### Requirement: Crawl4AIFetcher implements BaseFetcher interface

Crawl4AIFetcher SHALL implement the `BaseFetcher` abstract interface with `fetch()` and `close()` methods.

#### Scenario: Successful fetch returns HTML content
- **WHEN** Crawl4AIFetcher.fetch(url) is called with a valid URL
- **THEN** it returns a tuple of (status_code: int, html: str, response_headers: dict)

#### Scenario: Crawl4AIFetcher closes resources properly
- **WHEN** Crawl4AIFetcher.close() is called
- **THEN** the internal AsyncWebCrawler is properly shut down

### Requirement: Crawl4AIFetcher uses stealth mode

Crawl4AIFetcher SHALL enable stealth mode by default to avoid bot detection.

#### Scenario: Stealth mode is enabled
- **WHEN** Crawl4AIFetcher is initialized with stealth_enabled=True (default)
- **THEN** the BrowserConfig has enable_stealth=True

### Requirement: Crawl4AIFetcher supports configuration

Crawl4AIFetcher SHALL accept configuration parameters for customization.

#### Scenario: Custom configuration applied
- **WHEN** Crawl4AIFetcher is initialized with custom headless, stealth_enabled, user_agent, timeout
- **THEN** these values are applied to the internal BrowserConfig

### Requirement: Crawl4AIFetcher returns status code from response

Crawl4AIFetcher SHALL extract HTTP status code from CrawlResult.

#### Scenario: Status code extraction
- **WHEN** Crawl4AIFetcher.fetch(url) completes
- **THEN** the returned status_code matches result.status_code

### Requirement: Crawl4AIFetcher handles errors gracefully

Crawl4AIFetcher SHALL raise exceptions on failure for SmartFetcher to handle.

#### Scenario: Crawl failure raises exception
- **WHEN** Crawl4AIFetcher.fetch(url) fails (result.success=False)
- **THEN** an appropriate exception is raised with error message from result.error_message