## MODIFIED Requirements

### Requirement: Batch embedding cache retrieval
The LLM client SHALL use batch Redis operations for embedding cache lookups.

#### Scenario: Multiple embeddings fetched in one call
- **WHEN** `embed_texts()` is called with 32 texts
- **THEN** a single `MGET` command retrieves all cached embeddings
- **AND** Redis round trips are reduced from 32 to 1

#### Scenario: Cache miss handled per embedding
- **WHEN** some embeddings are cached and others are not
- **THEN** cached embeddings are returned immediately
- **AND** only uncached embeddings are sent to LLM API
- **AND** newly generated embeddings are cached individually

## ADDED Requirements

### Requirement: Cache key batch generation
Cache keys SHALL be generated in batch before Redis lookup.

#### Scenario: Keys generated before Redis call
- **WHEN** batch embedding is requested
- **THEN** all cache keys are generated first
- **AND** keys are sorted for consistent `MGET` ordering

### Requirement: Preserve individual cache writes
Cache writes after LLM calls SHALL remain individual for reliability.

#### Scenario: Individual writes on cache miss
- **WHEN** LLM returns embeddings for uncached texts
- **THEN** each embedding is cached with its own `SET` command
- **AND** a failure in one cache write does not affect others

### Requirement: Backward compatibility
The single `embed_text()` method SHALL work unchanged.

#### Scenario: Single embed still works
- **WHEN** `embed_text()` is called with one text
- **THEN** behavior is identical to pre-batch implementation