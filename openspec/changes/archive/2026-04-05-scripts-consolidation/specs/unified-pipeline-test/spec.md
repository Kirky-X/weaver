## ADDED Requirements

### Requirement: Support multiple pipeline test modes

The script SHALL support `--mode` parameter with values `newsnow`, `rss`, and `strategy` to test different data ingestion paths.

#### Scenario: NewsNow mode test
- **WHEN** user runs `scripts/test_pipeline.py --mode newsnow --max-items 5`
- **THEN** script fetches data from NewsNow API, processes through pipeline, and verifies storage

#### Scenario: RSS mode test
- **WHEN** user runs `scripts/test_pipeline.py --mode rss --source solidot --max-items 2`
- **THEN** script fetches data from RSS feed, processes through pipeline, and verifies storage

#### Scenario: Strategy mode test
- **WHEN** user runs `scripts/test_pipeline.py --mode strategy`
- **THEN** script tests database failover using `core.db.strategy.create_strategy()`

### Requirement: Reuse existing infrastructure modules

The script SHALL use `core.db.strategy.create_strategy()` for database initialization instead of duplicating connection logic.

#### Scenario: Database failover handling
- **WHEN** PostgreSQL is unavailable
- **THEN** script automatically falls back to DuckDB via `create_strategy()`

#### Scenario: Neo4j failover handling
- **WHEN** Neo4j is unavailable
- **THEN** script automatically falls back to LadybugDB via `create_strategy()`

### Requirement: Support article limit control

The script SHALL support `--max-items` parameter to limit the number of articles processed during testing.

#### Scenario: Limit articles processed
- **WHEN** user runs with `--max-items 3`
- **THEN** only 3 articles are fetched and processed

### Requirement: Support news mode forcing

The script SHALL support `--force-news` flag to bypass classifier and force all articles to be treated as news.

#### Scenario: Force news mode
- **WHEN** user runs with `--force-news`
- **THEN** all articles bypass classifier and are processed as news

### Requirement: Support database clearing

The script SHALL support `--clear-db` flag to clear test databases before running.

#### Scenario: Clear databases before test
- **WHEN** user runs with `--clear-db`
- **THEN** all tables in DuckDB and nodes in LadybugDB are cleared before processing