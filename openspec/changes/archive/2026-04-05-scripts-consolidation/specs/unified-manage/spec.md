## ADDED Requirements

### Requirement: Support validate and seed subcommands

The script SHALL support `validate` and `seed` subcommands to validate environment and seed database data respectively.

#### Scenario: Environment validation
- **WHEN** user runs `scripts/manage.py validate`
- **THEN** script validates PostgreSQL, Neo4j, Redis, LLM, and Embedding services

#### Scenario: Data seeding
- **WHEN** user runs `scripts/manage.py seed`
- **THEN** script seeds relation types and aliases into database

### Requirement: Reuse EnvironmentValidator module

The validate subcommand SHALL use `core.health.env_validator.EnvironmentValidator` instead of reimplementing validation logic.

#### Scenario: Validate all services
- **WHEN** user runs `scripts/manage.py validate`
- **THEN** EnvironmentValidator.validate_all() is called and results are printed

#### Scenario: Validate specific services
- **WHEN** user runs `scripts/manage.py validate --service postgres --service redis`
- **THEN** only PostgreSQL and Redis are validated

### Requirement: Support service selection

The validate subcommand SHALL support `--service` parameter to validate specific services.

#### Scenario: Validate single service
- **WHEN** user runs `scripts/manage.py validate --service llm`
- **THEN** only LLM provider is validated

### Requirement: Support reset option for seeding

The seed subcommand SHALL support `--reset` flag to clear existing data before seeding.

#### Scenario: Reset and seed
- **WHEN** user runs `scripts/manage.py seed --reset`
- **THEN** existing relation types are deleted and all types are re-inserted

#### Scenario: Incremental seed
- **WHEN** user runs `scripts/manage.py seed`
- **THEN** only missing relation types are inserted

### Requirement: Return appropriate exit codes

The script SHALL return exit code 0 on success, 1 on failure.

#### Scenario: Validation success
- **WHEN** all services are healthy
- **THEN** script exits with code 0

#### Scenario: Validation failure
- **WHEN** any service is unhealthy
- **THEN** script exits with code 1