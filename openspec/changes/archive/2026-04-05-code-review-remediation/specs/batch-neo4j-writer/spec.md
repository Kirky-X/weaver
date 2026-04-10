## ADDED Requirements

### Requirement: Batch write entities and relations
The Neo4j writer SHALL support batch writing of multiple pipeline states in a single transaction group.

#### Scenario: Batch write multiple articles
- **WHEN** `write_batch()` is called with 50 pipeline states
- **THEN** all entities are merged in a single UNWIND query
- **AND** all relations are created in a single UNWIND query
- **AND** network round trips are reduced to 2-3 from 50

#### Scenario: Batch write with deduplication
- **WHEN** multiple states contain the same entity name
- **THEN** the entity is created only once
- **AND** all relations reference the same entity node

### Requirement: Return batch write results
The batch write method SHALL return a mapping of state IDs to created Neo4j IDs.

#### Scenario: Successful batch write returns mapping
- **WHEN** `write_batch()` completes successfully
- **THEN** returns `{state_id: [neo4j_entity_ids]}` for each state
- **AND** callers can track which Neo4j nodes were created

#### Scenario: Partial failure returns partial results
- **WHEN** some states fail during batch write
- **THEN** returns results for successful states
- **AND** raises exception with list of failed state IDs

### Requirement: Maintain backward compatibility
The single `write()` method SHALL remain unchanged for existing callers.

#### Scenario: Single write still works
- **WHEN** `write()` is called with one state
- **THEN** behavior is identical to pre-batch-implementation
- **AND** existing tests pass without modification