## ADDED Requirements

### Requirement: Memory service injects vector repository
The Memory service SHALL accept and use an injected vector repository for semantic indexing in the Fast Path.

#### Scenario: Vector repository is injected
- **WHEN** Memory service is initialized with a vector repository
- **THEN** the SynapticIngestionService SHALL use the injected repository for event indexing

#### Scenario: Vector repository is optional
- **WHEN** Memory service is initialized without a vector repository
- **THEN** the SynapticIngestionService SHALL skip vector indexing operations

### Requirement: Memory service injects entity repository
The Memory service SHALL accept and use an injected entity repository for entity linking in the Fast Path.

#### Scenario: Entity repository is injected
- **WHEN** Memory service is initialized with an entity repository
- **THEN** the SynapticIngestionService SHALL use the injected repository for entity link updates

#### Scenario: Entity repository is optional
- **WHEN** Memory service is initialized without an entity repository
- **THEN** the SynapticIngestionService SHALL skip entity link operations

### Requirement: Entity link discovery status is documented
The entity link discovery in Slow Path SHALL have clear documentation explaining its implementation status.

#### Scenario: Entity link discovery documentation
- **WHEN** a developer reads the slow_path.py source code
- **THEN** they SHALL find a comment explaining why entity_links_added is currently zero and what is required for full implementation

### Requirement: Memory service exposes enriched search API
The Memory service SHALL provide a `search_with_context()` method that uses EntityAggregator, NarrativeSynthesizer, and SearchResponseBuilder.

#### Scenario: Search with context returns enriched response
- **WHEN** `search_with_context()` is called with a query
- **THEN** the response SHALL include aggregated entities, synthesized narrative, and structured result

#### Scenario: Search with context handles missing components gracefully
- **WHEN** `search_with_context()` is called without required dependencies
- **THEN** the method SHALL return a basic search result without enrichment

## MODIFIED Requirements

### Requirement: Memory service initializes with all dependencies
The MemoryIntegrationService SHALL accept all required repositories and services in its constructor.

#### Scenario: Full initialization
- **WHEN** Memory service is created with all dependencies (neo4j_pool, llm_client, redis_client, embedding_service, intent_classifier, vector_repo, entity_repo)
- **THEN** all internal services SHALL be properly initialized

#### Scenario: Partial initialization
- **WHEN** Memory service is created without optional dependencies (vector_repo, entity_repo)
- **THEN** the service SHALL still function with reduced capabilities