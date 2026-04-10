## ADDED Requirements

### Requirement: LLM TOML configuration supports hot reload

The system SHALL monitor `config/llm.toml` for file changes using watchfiles and automatically reload the configuration without requiring a service restart.

#### Scenario: TOML file modified
- **WHEN** `config/llm.toml` is modified and saved
- **THEN** the new configuration is loaded within 1 second
- **AND** all LLM components (SmartRouter, ProviderPool) receive the updated configuration

#### Scenario: Invalid TOML rejected
- **WHEN** `config/llm.toml` is saved with invalid TOML syntax
- **THEN** the configuration reload is rejected
- **AND** the previous valid configuration remains active
- **AND** an error is logged with the parse failure details

### Requirement: Atomic configuration swap

The LiveConfig SHALL use a two-phase update: first validate the new configuration against pydantic models, then atomically replace the in-memory configuration reference. If validation fails, the old configuration SHALL remain in place.

#### Scenario: Valid configuration swap
- **WHEN** a valid new TOML configuration is detected
- **THEN** pydantic validation succeeds
- **AND** the in-memory configuration is replaced atomically
- **AND** a reload event is emitted with the changed sections

#### Scenario: Validation failure preserves old config
- **WHEN** the new TOML has a valid syntax but invalid values (e.g., negative timeout)
- **THEN** pydantic validation fails
- **AND** the previous configuration is unchanged
- **AND** a warning is logged with validation errors

### Requirement: Routing configuration is extensible via TOML

The llm.toml file SHALL support additional `[routing.<call_point>]` sections that define per-call-point routing mode and weight overrides, without modifying existing `[defaults]` or `[call-points]` sections.

#### Scenario: Add routing section for existing call point
- **WHEN** `[routing.classifier]` section is added with `mode = "best"`
- **THEN** the classifier call point uses best mode weights
- **AND** existing `[call-points.classifier]` primary/fallbacks are preserved

#### Scenario: Remove routing section reverts to defaults
- **WHEN** `[routing.classifier]` section is removed from TOML
- **THEN** the classifier call point falls back to global default mode weights

### Requirement: Eval configuration via TOML

The llm.toml file SHALL support an `[eval]` section that enables shadow evaluation with configurable sample rate, target call points, and candidate models.

#### Scenario: Enable shadow evaluation
- **WHEN** `[eval]` section has `enabled = true` and `sample_rate = 0.1`
- **THEN** 10% of requests to target call points trigger parallel shadow calls
- **AND** shadow results are recorded for comparison

#### Scenario: Disable shadow evaluation
- **WHEN** `[eval]` section has `enabled = false`
- **THEN** no shadow calls are issued
- **AND** main call path is unaffected
