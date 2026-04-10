## ADDED Requirements

### Requirement: LLM configuration uses pydantic BaseModel

The LLM configuration types (`ProviderConfig`, `ModelConfig`, `RoutingConfig`, `GlobalConfig`) SHALL be defined as pydantic BaseModel classes instead of dataclass.

#### Scenario: LLM types are pydantic models
- **WHEN** `ProviderConfig` is imported
- **THEN** it is a subclass of `pydantic.BaseModel`
- **AND** all fields have type annotations

#### Scenario: LLM config validates on load
- **WHEN** `LLMSettings` is instantiated with invalid data
- **THEN** pydantic ValidationError is raised with field details

### Requirement: LLMSettings loads from dedicated TOML file

The LLMSettings class SHALL load configuration from `config/llm.toml` using pydantic-settings native TOML support.

#### Scenario: LLM TOML file loads correctly
- **WHEN** `LLMSettings()` is instantiated
- **THEN** configuration is loaded from `config/llm.toml`
- **AND** `settings.llm.providers` contains all defined providers

### Requirement: Environment variables override LLM TOML values

The LLM configuration SHALL support environment variable override using `WEAVER__LLM__<PATH>` format for any TOML value.

#### Scenario: Provider API key via environment variable
- **WHEN** `WEAVER__LLM__PROVIDERS__AIPING__API_KEY=sk-xxx` is set
- **THEN** `settings.llm.providers['aiping'].api_key` equals "sk-xxx"

#### Scenario: Global config via environment variable
- **WHEN** `WEAVER__LLM__GLOBAL_CONFIG__DEFAULT_TIMEOUT=180.0` is set
- **THEN** `settings.llm.global_config.default_timeout` equals 180.0

### Requirement: No custom ENV_VAR syntax

The LLM configuration SHALL NOT use the custom `${ENV_VAR}` syntax for environment variable references. All environment variable overrides SHALL use the standard pydantic-settings mechanism.

#### Scenario: No ${} syntax in TOML
- **WHEN** `llm.toml` is examined
- **THEN** no `${}` patterns exist in the file
- **AND** sensitive values are either empty strings or placeholder text

### Requirement: Dynamic provider keys supported

The LLM configuration SHALL support dynamic provider keys (e.g., `aiping`, `dmx`) via `dict[str, ProviderConfig]` type, with environment variable override using nested format.

#### Scenario: Dynamic provider configuration
- **WHEN** `llm.toml` contains `[providers.aiping]` and `[providers.dmx]`
- **THEN** `settings.llm.providers` is a dict with keys "aiping" and "dmx"

#### Scenario: Dynamic key environment override
- **WHEN** `WEAVER__LLM__PROVIDERS__NEWPROVIDER__API_KEY=sk-xxx` is set
- **THEN** `settings.llm.providers['newprovider'].api_key` equals "sk-xxx"

### Requirement: LLMConfigLoader removed

The custom `LLMConfigLoader` class SHALL be removed. All LLM configuration loading SHALL be handled by `LLMSettings` via pydantic-settings.

#### Scenario: No LLMConfigLoader import
- **WHEN** `LLMConfigLoader` is searched in the codebase
- **THEN** no import or usage exists

### Requirement: LLMSettings integrated into main Settings

The LLMSettings class SHALL be a sub-configuration of the main Settings class, accessible via `settings.llm`.

#### Scenario: LLM config accessible via main settings
- **WHEN** `settings = Settings()` is called
- **THEN** `settings.llm` returns LLMSettings instance
- **AND** all LLM configuration is accessible through this path