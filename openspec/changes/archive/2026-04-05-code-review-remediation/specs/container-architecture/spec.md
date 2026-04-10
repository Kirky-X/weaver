## MODIFIED Requirements

### Requirement: Container modular architecture
The dependency injection container SHALL be organized into focused modules with clear responsibilities.

#### Scenario: Access core services from module
- **WHEN** code needs settings or database strategy
- **THEN** `container.core.settings` and `container.core.strategy` are available
- **AND** the module `src/container/core.py` is < 300 lines

#### Scenario: Access repositories from factory
- **WHEN** code needs a repository instance
- **THEN** `container.repos.article_repo()` returns the repository
- **AND** the module `src/container/repos.py` handles all repository creation

#### Scenario: Legacy accessors still work
- **WHEN** code uses `container.article_repo()` (old style)
- **THEN** the call is delegated to the new module
- **AND** a deprecation warning is logged

## ADDED Requirements

### Requirement: Clear module boundaries
Each container module SHALL have a single responsibility.

#### Scenario: Core module responsibility
- **WHEN** reviewing `container/core.py`
- **THEN** it contains only settings, strategy, redis, and event bus initialization
- **AND** it does NOT contain repository or scheduler logic

#### Scenario: Scheduler module responsibility
- **WHEN** reviewing `container/scheduler.py`
- **THEN** it contains only `_setup_scheduler()` logic
- **AND** scheduler configuration is externalized to settings where possible

### Requirement: Deprecation timeline
Legacy accessors SHALL have a documented removal version.

#### Scenario: Deprecated accessor shows timeline
- **WHEN** using a deprecated accessor
- **THEN** warning message includes "removed in version 0.3.0"
- **AND** CHANGELOG documents the migration path