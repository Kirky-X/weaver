## ADDED Requirements

### Requirement: Settings class uses native TomlConfigSettingsSource

The Settings class SHALL use pydantic-settings native `TomlConfigSettingsSource` for TOML file loading, removing the custom `TomlSettingsSource` implementation.

#### Scenario: TOML file loads via native source
- **WHEN** Settings is instantiated
- **THEN** `config/settings.toml` is loaded via `TomlConfigSettingsSource`
- **AND** no custom TOML parsing code is executed

#### Scenario: Multiple TOML files supported
- **WHEN** `toml_file` is configured with multiple paths
- **THEN** files are merged in order with later files taking precedence

### Requirement: Environment variables override TOML values

The configuration system SHALL support environment variable override of any TOML value using the `WEAVER__<SECTION>__<FIELD>` naming format.

#### Scenario: Environment variable overrides TOML value
- **WHEN** `WEAVER__POSTGRES__HOST=db.example.com` is set in environment
- **THEN** `settings.postgres.host` equals "db.example.com"
- **AND** TOML value for `postgres.host` is ignored

#### Scenario: Nested configuration via environment variable
- **WHEN** `WEAVER__API__PORT=9000` is set in environment
- **THEN** `settings.api.port` equals 9000

### Requirement: Configuration priority follows defined order

The configuration system SHALL apply values in the following priority order (highest to lowest):
1. Environment variables
2. `.env` file
3. TOML configuration files
4. Code default values

#### Scenario: Priority chain applies correctly
- **WHEN** a configuration value exists in both TOML and environment variable
- **THEN** the environment variable value is used

### Requirement: Settings aggregates all sub-configurations

The Settings class SHALL aggregate all sub-configuration models as typed fields, providing a single entry point for all configuration access.

#### Scenario: Sub-configurations accessible via Settings
- **WHEN** `settings = Settings()` is called
- **THEN** `settings.postgres` returns PostgresSettings instance
- **AND** `settings.llm` returns LLMSettings instance
- **AND** `settings.pipeline` returns PipelineSettings instance

### Requirement: No custom field stripping logic

The Settings class SHALL NOT contain field stripping logic in `__init__` to handle environment variable precedence. The `settings_customise_sources` method SHALL handle all priority ordering.

#### Scenario: No manual field removal
- **WHEN** Settings source code is examined
- **THEN** no `pop()` or `del` operations exist for configuration fields in `__init__`

### Requirement: All sub-configurations use pydantic BaseModel

All configuration sections SHALL be defined as pydantic BaseModel classes with full type annotations and validation support.

#### Scenario: Sub-configurations validate types
- **WHEN** an invalid value is provided for a typed field
- **THEN** pydantic ValidationError is raised

#### Scenario: IDE autocomplete support
- **WHEN** developer types `settings.postgres.`
- **THEN** IDE shows all available fields with types