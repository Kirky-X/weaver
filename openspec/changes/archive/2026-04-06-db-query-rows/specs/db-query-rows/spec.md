## ADDED Requirements

### Requirement: Table rows query command
The system SHALL provide a `rows` subcommand to query data rows from a specified table.

#### Scenario: Query rows from PostgreSQL table
- **WHEN** user runs `uv run scripts/db_query.py rows articles --db postgres`
- **THEN** system displays rows from the articles table with default limit of 20

#### Scenario: Query rows from DuckDB table
- **WHEN** user runs `uv run scripts/db_query.py rows articles --db duckdb`
- **THEN** system displays rows from DuckDB articles table

#### Scenario: Query nodes from Neo4j
- **WHEN** user runs `uv run scripts/db_query.py rows Article --db neo4j`
- **THEN** system displays Article nodes with their properties

#### Scenario: Query nodes from LadybugDB
- **WHEN** user runs `uv run scripts/db_query.py rows Article --db ladybug`
- **THEN** system displays Article nodes from LadybugDB

#### Scenario: Invalid table name
- **WHEN** user specifies a table name with special characters
- **THEN** system rejects with error message indicating valid table name format

### Requirement: Pagination support
The system SHALL support pagination through `--limit` and `--page` parameters.

#### Scenario: Custom page size
- **WHEN** user runs `rows articles --limit 50`
- **THEN** system returns at most 50 rows

#### Scenario: Navigate to specific page
- **WHEN** user runs `rows articles --limit 20 --page 3`
- **THEN** system returns rows 41-60 (offset 40)

#### Scenario: Default pagination
- **WHEN** user runs `rows articles` without pagination parameters
- **THEN** system returns first 20 rows (page 1, limit 20)

### Requirement: Column selection
The system SHALL support selecting specific columns through `--columns` parameter.

#### Scenario: Select specific columns
- **WHEN** user runs `rows articles --columns id,title,category`
- **THEN** system returns only id, title, and category columns

#### Scenario: Default all columns
- **WHEN** user runs `rows articles` without `--columns`
- **THEN** system returns all columns (SELECT *)

#### Scenario: Invalid column name
- **WHEN** user specifies a non-existent column
- **THEN** system displays error from database and continues gracefully

### Requirement: Sorting support
The system SHALL support sorting through `--order-by` parameter.

#### Scenario: Sort ascending
- **WHEN** user runs `rows articles --order-by created_at`
- **THEN** system sorts results by created_at in ascending order

#### Scenario: Sort descending
- **WHEN** user runs `rows articles --order-by created_at:desc`
- **THEN** system sorts results by created_at in descending order

#### Scenario: Multiple column sort
- **WHEN** user runs `rows articles --order-by category --order-by created_at:desc`
- **THEN** system sorts by category ascending, then created_at descending

#### Scenario: No sorting
- **WHEN** user runs `rows articles` without `--order-by`
- **THEN** system returns rows in database default order

### Requirement: Output format support
The system SHALL support table and JSON output formats through `--format` parameter.

#### Scenario: Table output (default)
- **WHEN** user runs `rows articles`
- **THEN** system displays results in formatted table with column headers

#### Scenario: JSON output
- **WHEN** user runs `rows articles --format json`
- **THEN** system outputs results as JSON array to stdout

#### Scenario: Table truncation
- **WHEN** a column value exceeds display width
- **THEN** system truncates the value with ellipsis indicator

### Requirement: Graph database property handling
The system SHALL handle Neo4j and LadybugDB node properties as columns.

#### Scenario: Auto-detect node properties
- **WHEN** user queries Neo4j nodes without `--columns`
- **THEN** system returns all properties from the first matched node

#### Scenario: Property filter
- **WHEN** user runs `rows Entity --columns name,type --db neo4j`
- **THEN** system returns only name and type properties for Entity nodes