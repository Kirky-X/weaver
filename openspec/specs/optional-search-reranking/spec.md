## ADDED Requirements

### Requirement: Flashrank as optional dependency

The system SHALL provide flashrank as an optional dependency for search result re-ranking.

**Rationale**: Reranking is an optional enhancement. Systems without flashrank should still function with degraded search quality.

#### Scenario: System with flashrank installed
- **WHEN** flashrank is installed and `search.rerank_enabled=true`
- **THEN** the system SHALL use FlashrankReranker for cross-encoder re-ranking
- **AND** search results SHALL have improved relevance scores

#### Scenario: System without flashrank
- **WHEN** flashrank is NOT installed and `search.rerank_enabled=true`
- **THEN** the system SHALL log a warning `flashrank_reranker_init_failed`
- **AND** search SHALL continue without reranking
- **AND** HybridSearchEngine SHALL return BM25+vector fusion results only

### Requirement: Optional dependency installation

The system SHALL support installing flashrank via optional dependency group.

#### Scenario: Install search-enhancement optional group
- **WHEN** user runs `uv pip install ".[search-enhancement]"`
- **THEN** flashrank package SHALL be installed
- **AND** reranking functionality SHALL be available

#### Scenario: Default installation without optional group
- **WHEN** user runs `uv pip install .`
- **THEN** flashrank package SHALL NOT be installed by default
- **AND** core search functionality SHALL work without reranking

### Requirement: Graceful degradation

The system SHALL gracefully degrade when flashrank is unavailable.

#### Scenario: Reranker initialization failure
- **WHEN** FlashrankReranker initialization fails for any reason
- **THEN** container.py SHALL catch the exception
- **AND** log a warning message
- **AND** HybridSearchEngine.search() SHALL skip reranking step
- **AND** no user-facing error SHALL occur