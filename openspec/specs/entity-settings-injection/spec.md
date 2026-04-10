# Spec: Entity Settings Injection

## ADDED Requirements

### Requirement: EntitySettings configuration SHALL be injected into EntityResolver

The system SHALL pass the `disable_data_metrics_nodes` configuration from `EntitySettings` to the `EntityResolver` component during initialization.

#### Scenario: Configuration disabled by default
- **WHEN** no explicit configuration is provided
- **THEN** `EntityResolver.disable_data_metrics` SHALL be `False`

#### Scenario: Configuration enabled via settings
- **WHEN** `entity.disable_data_metrics_nodes=true` is configured
- **THEN** `EntityResolver.disable_data_metrics` SHALL be `True`

#### Scenario: Data metrics entities filtered when enabled
- **WHEN** `disable_data_metrics_nodes=true` AND an entity of type "数据指标" is processed
- **THEN** the entity SHALL be filtered out and not persisted to the graph

### Requirement: Configuration injection SHALL be consistent across components

All components that filter data metrics entities SHALL receive the same configuration value.

#### Scenario: spaCy extractor receives configuration
- **WHEN** `entity_extractor.py` calls `spacy_extractor.extract()`
- **THEN** the `disable_data_metrics` parameter SHALL match `EntitySettings.disable_data_metrics_nodes`

#### Scenario: LLM entity extractor receives configuration
- **WHEN** `entity_extractor.py` processes LLM-extracted entities
- **THEN** the filtering logic SHALL apply the same `disable_data_metrics` setting