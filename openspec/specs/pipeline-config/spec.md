## ADDED Requirements

### Requirement: Pipeline configuration uses pydantic BaseModel

The Pipeline configuration types (`StageConfig`, `PhaseConfig`, `BatchConfig`) SHALL be defined as pydantic BaseModel classes instead of dataclass.

#### Scenario: Pipeline types are pydantic models
- **WHEN** `StageConfig` is imported
- **THEN** it is a subclass of `pydantic.BaseModel`
- **AND** all fields have type annotations

#### Scenario: Pipeline config validates on load
- **WHEN** `PipelineSettings` is instantiated with invalid stage config
- **THEN** pydantic ValidationError is raised

### Requirement: Pipeline configuration uses TOML format

The Pipeline configuration SHALL be stored in `config/pipeline.toml` instead of YAML format.

#### Scenario: Pipeline TOML file loads correctly
- **WHEN** `PipelineSettings()` is instantiated
- **THEN** configuration is loaded from `config/pipeline.toml`
- **AND** no YAML parsing code is executed

#### Scenario: TOML format supports stages array
- **WHEN** `pipeline.toml` contains `[[phase1.stages]]` entries
- **THEN** `settings.pipeline.phase1.stages` is a list of StageConfig instances

### Requirement: Environment variables override Pipeline TOML values

The Pipeline configuration SHALL support environment variable override using `WEAVER__PIPELINE__<PATH>` format.

#### Scenario: Phase concurrency via environment variable
- **WHEN** `WEAVER__PIPELINE__PHASE1__CONCURRENCY=10` is set
- **THEN** `settings.pipeline.phase1.concurrency` equals 10

#### Scenario: Stage timeout via environment variable
- **WHEN** `WEAVER__PIPELINE__PHASE1__STAGES__0__TIMEOUT=120` is set
- **THEN** `settings.pipeline.phase1.stages[0].timeout` equals 120

### Requirement: PipelineConfigLoader removed

The custom `PipelineConfigLoader` class SHALL be removed. All Pipeline configuration loading SHALL be handled by `PipelineSettings` via pydantic-settings.

#### Scenario: No PipelineConfigLoader import
- **WHEN** `PipelineConfigLoader` is searched in the codebase
- **THEN** no import or usage exists

### Requirement: PipelineSettings integrated into main Settings

The PipelineSettings class SHALL be a sub-configuration of the main Settings class, accessible via `settings.pipeline`.

#### Scenario: Pipeline config accessible via main settings
- **WHEN** `settings = Settings()` is called
- **THEN** `settings.pipeline` returns PipelineSettings instance
- **AND** all pipeline configuration is accessible through this path

### Requirement: Default pipeline configuration provided

The PipelineSettings class SHALL provide a `default()` class method that returns a valid default configuration matching the existing hardcoded defaults.

#### Scenario: Default configuration is valid
- **WHEN** `PipelineSettings.default()` is called
- **THEN** a valid PipelineSettings instance is returned
- **AND** `phase1.stages` contains classifier, cleaner, categorizer, vectorize stages
- **AND** `phase3.stages` contains re_vectorize, analyze, quality_scorer, credibility, entity_extractor stages

### Requirement: Enabled stages property

The PhaseConfig class SHALL provide an `enabled_stages` property that returns only stages where `enabled=True`.

#### Scenario: Filter disabled stages
- **WHEN** `phase1.stages` contains 4 stages with one disabled
- **THEN** `phase1.enabled_stages` returns 3 StageConfig instances