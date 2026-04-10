## ADDED Requirements

### Requirement: Crawler validates all content uniformly

Crawler SHALL validate all content using trafilatura extraction, regardless of source (pre-filled body or fetched HTML).

#### Scenario: Pre-filled HTML content is validated
- **WHEN** NewsItem.body contains HTML content (detected by HTML tags)
- **THEN** trafilatura.extract() is called on the content

#### Scenario: Pre-filled plain text is preserved
- **WHEN** NewsItem.body contains plain text (no HTML tags) AND trafilatura returns None
- **THEN** the original text is preserved as-is

### Requirement: Crawler re-fetches when validation fails

Crawler SHALL re-fetch the URL with force_browser=True when trafilatura extraction yields insufficient content.

#### Scenario: Content too short triggers re-fetch
- **WHEN** extracted body length is less than MIN_ARTICLE_LENGTH (100 chars)
- **THEN** fetcher.fetch(url, force_browser=True) is called

#### Scenario: Re-fetch content is extracted again
- **WHEN** re-fetch with force_browser=True succeeds
- **THEN** trafilatura.extract() is called on the new HTML

### Requirement: MIN_ARTICLE_LENGTH threshold is configurable

The minimum article length threshold SHALL be defined as a constant.

#### Scenario: Threshold value
- **WHEN** content validation checks length
- **THEN** MIN_ARTICLE_LENGTH is used (default: 100 characters)

### Requirement: Validation failures are logged

Crawler SHALL log validation failures for debugging.

#### Scenario: Pre-filled body insufficient logged
- **WHEN** pre-filled body fails validation
- **THEN** a debug log entry is created with URL

#### Scenario: First fetch validation failed logged
- **WHEN** first fetch content fails validation
- **THEN** a debug log entry is created with URL