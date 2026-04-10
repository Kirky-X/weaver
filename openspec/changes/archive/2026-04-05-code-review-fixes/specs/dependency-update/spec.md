## ADDED Requirements

### Requirement: Dependencies are up to date

The system SHALL have all direct dependencies updated to their latest stable versions.

#### Scenario: Security-critical packages updated
- **WHEN** running `uv pip list --outdated`
- **THEN** the following packages SHALL be at their latest versions:
  - `sqlalchemy` >= 2.0.49
  - `anthropic` >= 0.89.0
  - `numpy` >= 2.4.4

#### Scenario: All tests pass after update
- **WHEN** running `uv run pytest --cov=src`
- **THEN** test coverage SHALL remain >= 80%
- **AND** all tests SHALL pass

### Requirement: Dependency update is reproducible

The system SHALL have a lock file that ensures reproducible builds.

#### Scenario: Lock file is updated
- **WHEN** running `uv lock --upgrade`
- **THEN** `uv.lock` SHALL be updated with new versions
- **AND** `uv sync` SHALL install consistent versions