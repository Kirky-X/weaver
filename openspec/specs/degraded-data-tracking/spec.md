## ADDED Requirements

### Requirement: Track degraded data fields
Pipeline nodes SHALL record which output fields were produced by fallback rather than normal processing.

#### Scenario: LLM cleaner fallback marks degraded
- **WHEN** LLM cleaner fails and raw data is used as fallback
- **THEN** `state["degraded_fields"]` contains `"cleaned"`
- **AND** `state["degradation_reasons"]` contains error description

#### Scenario: Entity extractor fallback marks degraded
- **WHEN** entity extraction fails and empty list is returned
- **THEN** `state["degraded_fields"]` contains `"entities"`
- **AND** downstream nodes can check for degraded input

### Requirement: Preserve degradation info through pipeline
Degradation markers SHALL be preserved through the entire pipeline execution.

#### Scenario: Degradation info persists to storage
- **WHEN** an article with degraded fields is persisted
- **THEN** degradation info is stored in article metadata
- **AND** can be queried for data quality audits

### Requirement: Provide degradation summary
The pipeline state SHALL provide a method to check if data is degraded.

#### Scenario: Check if state has degraded data
- **WHEN** `state.has_degraded_data()` is called
- **THEN** returns `True` if any field is marked degraded
- **AND** `state.get_degradation_summary()` returns human-readable summary