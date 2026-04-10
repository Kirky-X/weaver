## ADDED Requirements

### Requirement: Output format parameter
The system SHALL accept a `--format` parameter to specify output format for query results.

#### Scenario: Table format (default)
- **WHEN** user runs any subcommand without `--format`
- **THEN** system outputs results in formatted table

#### Scenario: JSON format
- **WHEN** user runs `rows articles --format json`
- **THEN** system outputs results as JSON array to stdout

#### Scenario: Invalid format
- **WHEN** user specifies `--format invalid`
- **THEN** system displays error listing valid formats (table, json)