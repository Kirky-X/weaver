## ADDED Requirements

### Requirement: LadybugDB graph statistics query
The system SHALL provide LadybugDB node and relationship counts through the `db_query.py stats --db ladybug` command.

#### Scenario: Query all LadybugDB graph elements
- **WHEN** user runs `uv run scripts/db_query.py stats --db ladybug`
- **THEN** system displays node counts for Article and Entity labels, and relationship counts for MENTIONS, FOLLOWED_BY, RELATED_TO types

#### Scenario: LadybugDB database not enabled
- **WHEN** user runs `stats --db ladybug` and `settings.ladybug.enabled` is False
- **THEN** system displays message indicating LadybugDB is not enabled

#### Scenario: LadybugDB connection failure
- **WHEN** LadybugDB database file is inaccessible
- **THEN** system displays error message and continues (does not crash)

### Requirement: LadybugDB random articles query
The system SHALL provide random article retrieval from LadybugDB through the `db_query.py random --db ladybug` command.

#### Scenario: Query random articles
- **WHEN** user runs `random --limit 3 --db ladybug`
- **THEN** system returns 3 random articles with their entities and relationships from LadybugDB

#### Scenario: No articles in database
- **WHEN** LadybugDB has no Article nodes
- **THEN** system displays "no articles found" message

### Requirement: LadybugDB output format consistency
LadybugDB query output SHALL match Neo4j output format for the same query type.

#### Scenario: Stats output format
- **WHEN** user queries LadybugDB stats
- **THEN** output format matches Neo4j stats output (label/relationship type, count, status columns)

#### Scenario: Random output format
- **WHEN** user queries random articles from LadybugDB
- **THEN** output format matches Neo4j random output