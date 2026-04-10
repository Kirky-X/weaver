## ADDED Requirements

### Requirement: Database selection parameter
The system SHALL accept a `--db` parameter for specifying which database(s) to query.

#### Scenario: Single database selection
- **WHEN** user runs `stats --db postgres`
- **THEN** system queries only PostgreSQL database

#### Scenario: Multiple database selection
- **WHEN** user runs `stats --db postgres --db duckdb`
- **THEN** system queries both specified databases and displays results for each

#### Scenario: No database specified for stats
- **WHEN** user runs `stats` without `--db` parameter
- **THEN** system queries all enabled databases (postgres, duckdb if enabled, neo4j, ladybug if enabled)

#### Scenario: No database specified for article
- **WHEN** user runs `article --id <uuid>` without `--db` parameter
- **THEN** system queries PostgreSQL by default

#### Scenario: No database specified for random
- **WHEN** user runs `random --limit 3` without `--db` parameter
- **THEN** system queries Neo4j by default

### Requirement: Invalid database parameter handling
The system SHALL reject invalid database names with clear error message.

#### Scenario: Invalid database name
- **WHEN** user runs `stats --db invalid_db`
- **THEN** system displays error: "Invalid database 'invalid_db'. Valid options: postgres, duckdb, neo4j, ladybug"

### Requirement: Database status indication
The system SHALL indicate database status in output when database is skipped.

#### Scenario: Database disabled
- **WHEN** user runs `stats` and DuckDB is disabled (`enabled=False`)
- **THEN** output includes "DuckDB: skipped (disabled in settings)"

#### Scenario: Database connection failed
- **WHEN** database connection fails
- **THEN** output includes database name with error message, other databases continue