## MODIFIED Requirements

### Requirement: LLM usage hourly table schema
The system SHALL define the `llm_usage_hourly` table with column names matching the SQLAlchemy model definition.

#### Scenario: Hourly aggregation column
- **WHEN** querying LLM usage by hour
- **THEN** the time bucket column is named `time_bucket` (not `hour_timestamp`)

#### Scenario: Schema-model consistency
- **WHEN** the DuckDB schema is initialized
- **THEN** the llm_usage_hourly table columns match the SQLAlchemy model field names

#### Scenario: LLM usage API query
- **WHEN** the `/api/v1/admin/llm-usage` endpoint is called with DuckDB backend
- **THEN** the query succeeds without column name errors

### Requirement: Schema migration safety
The system SHALL handle schema changes safely without data loss in development environments.

#### Scenario: Fresh database creation
- **WHEN** a new DuckDB file is created
- **THEN** the correct schema with `time_bucket` column is used

#### Scenario: Existing database handling
- **WHEN** an existing DuckDB file has the old schema
- **THEN** the schema migration renames the column or recreates the table