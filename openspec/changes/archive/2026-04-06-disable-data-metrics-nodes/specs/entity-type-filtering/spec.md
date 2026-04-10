## ADDED Requirements

### Requirement: Entity type filtering configuration
The system SHALL provide a configuration option to disable extraction of specific entity types.

#### Scenario: Configuration default allows all entity types
- **WHEN** `disable_data_metrics_nodes` is not set
- **THEN** all entity types including "数据指标" are extracted and stored

#### Scenario: Configuration disables data metrics extraction
- **WHEN** `disable_data_metrics_nodes` is set to `true`
- **THEN** entities of type "数据指标" are not extracted or stored

### Requirement: SpaCy stage filtering
The spaCy extractor SHALL skip "数据指标" entity generation when configured.

#### Scenario: SpaCy skips CARDINAL entities when disabled
- **WHEN** `disable_data_metrics_nodes` is `true`
- **AND** spaCy NER detects a `CARDINAL` entity
- **THEN** no "数据指标" entity is created

#### Scenario: SpaCy skips PERCENT entities when disabled
- **WHEN** `disable_data_metrics_nodes` is `true`
- **AND** spaCy NER detects a `PERCENT` entity
- **THEN** no "数据指标" entity is created

#### Scenario: SpaCy skips MONEY entities when disabled
- **WHEN** `disable_data_metrics_nodes` is `true`
- **AND** spaCy NER detects a `MONEY` entity
- **THEN** no "数据指标" entity is created

### Requirement: LLM stage filtering
The LLM entity extractor SHALL filter out "数据指标" entities from LLM results when configured.

#### Scenario: LLM entities filtered when disabled
- **WHEN** `disable_data_metrics_nodes` is `true`
- **AND** LLM returns entities with `type: "数据指标"`
- **THEN** those entities are removed from the result set
- **AND** other entity types remain unaffected

### Requirement: Configuration structure
The entity filtering configuration SHALL follow the project's nested configuration pattern.

#### Scenario: Environment variable configuration
- **WHEN** environment variable `WEAVER_ENTITY__DISABLE_DATA_METRICS_NODES` is set to `true`
- **THEN** `settings.entity.disable_data_metrics_nodes` returns `true`

#### Scenario: TOML file configuration
- **WHEN** `settings.toml` contains `[entity]\ndisable_data_metrics_nodes = true`
- **THEN** `settings.entity.disable_data_metrics_nodes` returns `true`