## ADDED Requirements

### Requirement: Graph query builder abstraction
The system SHALL provide a `GraphQueryBuilder` protocol that abstracts database-specific query syntax differences between Neo4j Cypher and LadybugDB SQL variant.

#### Scenario: Neo4j entity search query
- **WHEN** building an entity search query for Neo4j
- **THEN** the query uses Cypher syntax with `MATCH (e:Entity) WHERE ... RETURN e`

#### Scenario: LadybugDB entity search query
- **WHEN** building an entity search query for LadybugDB
- **THEN** the query uses SQL-like syntax compatible with LadybugDB's query engine

### Requirement: Query builder factory
The system SHALL provide a factory function that returns the appropriate query builder based on graph database type.

#### Scenario: Neo4j query builder selection
- **WHEN** the graph type is "neo4j"
- **THEN** the factory returns a Neo4jQueryBuilder instance

#### Scenario: LadybugDB query builder selection
- **WHEN** the graph type is "ladybug"
- **THEN** the factory returns a LadybugQueryBuilder instance

### Requirement: Entity search query support
The system SHALL support building entity search queries that work across Neo4j and LadybugDB.

#### Scenario: Entity name contains query
- **WHEN** searching for entities where name contains a substring
- **THEN** the query builder generates appropriate syntax for each database

#### Scenario: Entity type filter query
- **WHEN** filtering entities by type
- **THEN** the query builder handles type checking syntax differences

### Requirement: Relationship query support
The system SHALL support building relationship traversal queries that work across Neo4j and LadybugDB.

#### Scenario: Outgoing relationships query
- **WHEN** querying outgoing relationships from an entity
- **THEN** the query builder generates appropriate MATCH/JOIN syntax

#### Scenario: Relationship type filtering
- **WHEN** filtering relationships by type
- **THEN** the query builder handles TYPE() function (Neo4j) vs alternative approach (LadybugDB)

### Requirement: Community query support
The system SHALL support building community detection queries that work across Neo4j and LadybugDB.

#### Scenario: Community members query
- **WHEN** querying members of a community
- **THEN** the query builder generates appropriate syntax

#### Scenario: Community hierarchy query
- **WHEN** querying community parent-child relationships
- **THEN** the query builder handles hierarchical traversal

### Requirement: Temporal query support
The system SHALL support building time-based queries that work across Neo4j and LadybugDB.

#### Scenario: Event time range query
- **WHEN** querying events within a time range
- **THEN** the query builder generates appropriate timestamp comparison syntax

#### Scenario: Event ordering query
- **WHEN** ordering events by time
- **THEN** the query builder handles ORDER BY with timestamp fields