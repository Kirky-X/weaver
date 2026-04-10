## ADDED Requirements

### Requirement: DuckDB table statistics query
The system SHALL provide DuckDB table record counts through the `db_query.py stats --db duckdb` command.

#### Scenario: Query all DuckDB tables
- **WHEN** user runs `uv run scripts/db_query.py stats --db duckdb`
- **THEN** system displays record counts for all tables including articles, article_vectors, entity_vectors, llm_usage_raw, sources, pending_sync, etc.

#### Scenario: DuckDB database not enabled
- **WHEN** user runs `stats --db duckdb` and `settings.duckdb.enabled` is False
- **THEN** system displays message indicating DuckDB is not enabled

#### Scenario: DuckDB connection failure
- **WHEN** DuckDB database file is inaccessible
- **THEN** system displays error message and continues (does not crash)

### Requirement: DuckDB article query by ID
The system SHALL provide article retrieval from DuckDB through the `db_query.py article --id <uuid> --db duckdb` command.

#### Scenario: Query existing article
- **WHEN** user runs `article --id <valid-uuid> --db duckdb`
- **THEN** system displays article data from DuckDB articles table

#### Scenario: Article not found
- **WHEN** user queries non-existent article ID
- **THEN** system displays "article not found" message

### Requirement: DuckDB output format consistency
DuckDB query output SHALL match PostgreSQL output format for the same query type.

#### Scenario: Stats output format
- **WHEN** user queries DuckDB stats
- **THEN** output format matches PostgreSQL stats output (table name, record count, status columns)

#### Scenario: Article output format
- **WHEN** user queries article from DuckDB
- **THEN** output format matches PostgreSQL article output