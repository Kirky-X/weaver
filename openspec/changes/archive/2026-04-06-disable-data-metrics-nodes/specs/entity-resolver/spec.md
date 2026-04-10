## ADDED Requirements

### Requirement: Configuration-driven entity type filtering
The entity resolver SHALL check configuration before processing "数据指标" entities.

#### Scenario: Resolver skips data metrics when configured
- **WHEN** `disable_data_metrics_nodes` is `true`
- **AND** `resolve_entity()` is called with `entity_type: "数据指标"`
- **THEN** the resolver returns a filtered result immediately
- **AND** no entity is created in the knowledge graph

#### Scenario: Resolver processes data metrics when not configured
- **WHEN** `disable_data_metrics_nodes` is `false` or not set
- **AND** `resolve_entity()` is called with `entity_type: "数据指标"`
- **THEN** normal resolution logic proceeds
- **AND** existing `_looks_like_metric_string` check is still applied

#### Scenario: Configuration takes precedence over string check
- **WHEN** both `disable_data_metrics_nodes` is `true`
- **AND** the entity name looks like a metric string
- **THEN** the configuration check is evaluated first
- **AND** no redundant string check is performed