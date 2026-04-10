## ADDED Requirements

### Requirement: Community node table
The system SHALL define a `Community` node table in LadybugDB schema with appropriate properties.

#### Scenario: Community table creation
- **WHEN** LadybugDB schema is initialized
- **THEN** the Community table is created with id, title, summary, level, rank, parent_id, and created_at columns

#### Scenario: Community primary key
- **WHEN** creating the Community table
- **THEN** the id column is defined as PRIMARY KEY

#### Scenario: Community hierarchy support
- **WHEN** creating the Community table
- **THEN** the parent_id column supports storing parent community ID
- **AND** parent_id can be NULL (for root communities)

#### Scenario: Community hierarchy query
- **WHEN** querying community hierarchy
- **THEN** child communities can be found via parent_id
- **AND** parent community chain can be traced

### Requirement: CommunityReport node table
The system SHALL define a `CommunityReport` node table in LadybugDB schema with appropriate properties including vector embedding.

#### Scenario: CommunityReport table creation
- **WHEN** LadybugDB schema is initialized
- **THEN** the CommunityReport table is created with id, community_id, title, summary, full_content, full_content_embedding, and created_at columns

#### Scenario: CommunityReport embedding column
- **WHEN** creating the CommunityReport table
- **THEN** the full_content_embedding column is defined as FLOAT[1024] for vector storage

### Requirement: HAS_ENTITY relationship table
The system SHALL define a `HAS_ENTITY` relationship table linking communities to entities.

#### Scenario: HAS_ENTITY table creation
- **WHEN** LadybugDB schema is initialized
- **THEN** the HAS_ENTITY relationship table is created with FROM Community TO Entity

#### Scenario: HAS_ENTITY relationship query
- **WHEN** querying community members
- **THEN** the HAS_ENTITY relationship can be traversed bidirectionally

### Requirement: REPORTS_ON relationship table
The system SHALL define a `REPORTS_ON` relationship table linking community reports to communities.

#### Scenario: REPORTS_ON table creation
- **WHEN** LadybugDB schema is initialized
- **THEN** the REPORTS_ON relationship table is created with FROM CommunityReport TO Community

#### Scenario: REPORTS_ON relationship query
- **WHEN** querying community reports
- **THEN** the REPORTS_ON relationship links reports to their subject communities