## ADDED Requirements

### Requirement: Batch progress tracking

The Pipeline SHALL track and log progress statistics for each article processed within a batch.

Progress statistics SHALL include:
- Total articles in batch
- Completed articles count
- Failed articles count
- Success rate percentage
- Current article URL

#### Scenario: Single article successfully processed

- **WHEN** an article is successfully persisted to both Postgres and Neo4j
- **THEN** the system SHALL output a progress log with updated counts and success rate
- **AND** the log format SHALL be `[{completed}/{total}] {rate}% success ({failed} failed) | {url}`

#### Scenario: Single article persistence failed

- **WHEN** an article fails to persist to Postgres or Neo4j
- **THEN** the system SHALL increment the failed count
- **AND** the progress log SHALL reflect the failure in the failed count

#### Scenario: Terminal article skipped

- **WHEN** an article is marked as terminal (non-news)
- **THEN** the system SHALL NOT count it as completed or failed
- **AND** the progress log SHALL NOT include terminal articles in the counts

#### Scenario: Multiple batches processed sequentially

- **WHEN** a second batch starts processing
- **THEN** the progress counters SHALL be reset to zero
- **AND** progress logs SHALL only reflect the current batch

### Requirement: Progress log output timing

The progress log SHALL be output after each article completes the entire pipeline processing.

#### Scenario: Progress logged after persist

- **WHEN** an article finishes the persist phase
- **THEN** the system SHALL output exactly one progress log entry for that article

### Requirement: Failure definition

An article SHALL be counted as failed if and only if persistence to Postgres OR Neo4j fails.

#### Scenario: Postgres write fails

- **WHEN** Postgres write fails and article_id is not set
- **THEN** the article SHALL be counted as failed

#### Scenario: Neo4j write fails

- **WHEN** Neo4j write throws an exception
- **THEN** the article SHALL be counted as failed

#### Scenario: LLM degradation but persist succeeds

- **WHEN** LLM calls fail but fallback values are used
- **AND** the article is successfully persisted
- **THEN** the article SHALL be counted as successful (not failed)