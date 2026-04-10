## MODIFIED Requirements

### Requirement: Search engine backend support
The system SHALL support both Neo4j and LadybugDB as graph database backends for search engines.

#### Scenario: Neo4j search engine initialization
- **WHEN** the graph type is "neo4j"
- **THEN** the search engine is initialized with Neo4jContextBuilder

#### Scenario: LadybugDB search engine initialization
- **WHEN** the graph type is "ladybug"
- **THEN** the search engine is initialized with LadybugContextBuilder

#### Scenario: Search endpoint availability
- **WHEN** the `/api/v1/search` endpoint is called with LadybugDB backend
- **THEN** the endpoint returns search results instead of 503 error

### Requirement: Local search context builder
The system SHALL provide a LadybugDB-specific implementation of LocalContextBuilder.

#### Scenario: LadybugDB context building
- **WHEN** building search context from LadybugDB
- **THEN** the context builder uses LadybugDB-compatible queries

#### Scenario: Entity retrieval for search
- **WHEN** retrieving entities for local search context
- **THEN** the LadybugContextBuilder queries the Entity table correctly

### Requirement: Global search context builder
The system SHALL provide a LadybugDB-specific implementation of GlobalContextBuilder.

#### Scenario: Community retrieval for search
- **WHEN** building global search context
- **THEN** the LadybugContextBuilder queries the Community and CommunityReport tables

#### Scenario: Community report vector search
- **WHEN** searching for relevant community reports
- **THEN** the LadybugContextBuilder performs similarity search (with full scan if vector index unavailable)

### Requirement: Search engine strategy selection
The system SHALL select the appropriate search context builder based on graph database type without hardcoding exclusions.

#### Scenario: Container strategy selection
- **WHEN** the container initializes search engines
- **THEN** the graph type determines which context builder to use

#### Scenario: LadybugDB not excluded
- **WHEN** graph_type is "ladybug"
- **THEN** the search engine is NOT automatically skipped

### Requirement: DRIFT search endpoint dependencies

The system SHALL obtain database connections and LLM clients through dependency injection rather than direct attribute access.

#### Scenario: DRIFT search with dependency injection
- **WHEN** calling the `/search/drift` endpoint
- **THEN** it obtains `neo4j_pool` and `llm_client` from `deps.Endpoints`
- **AND** it does not directly access `global_engine._pool` or `global_engine._llm`

#### Scenario: DRIFT search LadybugDB compatibility
- **WHEN** using LadybugDB backend
- **THEN** DRIFT search successfully returns results
- **AND** it does not raise AttributeError

### Requirement: DRIFT engine initialization

The system SHALL create DRIFTSearchEngine with correct initialization parameters.

#### Scenario: DRIFT engine pool access
- **WHEN** creating DRIFTSearchEngine
- **THEN** it obtains the pool parameter from dependency injection
- **AND** the pool can be either Neo4jPool or LadybugPool

#### Scenario: DRIFT engine LLM access
- **WHEN** creating DRIFTSearchEngine
- **THEN** it obtains the llm parameter from dependency injection