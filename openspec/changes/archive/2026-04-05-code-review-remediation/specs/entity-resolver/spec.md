## MODIFIED Requirements

### Requirement: Modular entity matching
The entity resolver SHALL use separate methods for each matching strategy.

#### Scenario: Exact match extracted to method
- **WHEN** reviewing `entity_resolver.py`
- **THEN** `_try_exact_match()` handles exact name lookup
- **AND** the method is < 30 lines and independently testable

#### Scenario: Fuzzy match extracted to method
- **WHEN** reviewing `entity_resolver.py`
- **THEN** `_try_fuzzy_match()` handles vector similarity search
- **AND** the method returns match results with confidence scores

#### Scenario: Entity creation extracted to method
- **WHEN** reviewing `entity_resolver.py`
- **THEN** `_create_new_entity()` handles new entity creation
- **AND** the method encapsulates all creation logic including embedding

## ADDED Requirements

### Requirement: Resolve function under 100 lines
The main `resolve_entity()` method SHALL be under 100 lines.

#### Scenario: Main function orchestrates matchers
- **WHEN** `resolve_entity()` is called
- **THEN** it delegates to `_try_exact_match()`, `_try_alias_match()`, `_try_fuzzy_match()`
- **AND** the function is easy to read and understand

### Requirement: Consistent return types
All match methods SHALL return consistent types.

#### Scenario: Match methods return optional result
- **WHEN** any match method is called
- **THEN** it returns `ResolvedMatch | None`
- **AND** `ResolvedMatch` includes `neo4j_id`, `match_type`, `confidence`

### Requirement: Null embedding handling
Entity resolver SHALL handle missing embeddings gracefully.

#### Scenario: No embedding falls back to name-only match
- **WHEN** embedding is None or empty
- **THEN** entity is created without vector
- **AND** exact name match is still attempted first
- **AND** degradation is logged for monitoring