## ADDED Requirements

### Requirement: PhishTank data synchronization
The system SHALL periodically download and cache PhishTank phishing URL data.

#### Scenario: Initial data load
- **WHEN** PhishTankSync is initialized
- **AND** local data file exists
- **THEN** the system loads data from local file

#### Scenario: First time sync
- **WHEN** PhishTankSync is initialized
- **AND** local data file does not exist
- **THEN** the system downloads data from PhishTank

#### Scenario: Periodic sync
- **WHEN** sync interval has elapsed since last sync
- **THEN** the system downloads fresh data from PhishTank
- **AND** updates local cache file

### Requirement: Local URL lookup
The system SHALL provide fast URL lookup against cached PhishTank data.

#### Scenario: Exact URL match
- **WHEN** URL exists in PhishTank cache
- **THEN** returns BLOCKED risk level
- **AND** includes phish_id and target information

#### Scenario: Domain match
- **WHEN** URL domain has known phishing URLs
- **AND** exact URL not in cache
- **THEN** returns HIGH risk level
- **AND** includes phishing URL count for domain

#### Scenario: URL not found
- **WHEN** URL and domain not in PhishTank cache
- **THEN** returns SAFE risk level

### Requirement: Index management
The system SHALL maintain dual indexes for efficient lookup.

#### Scenario: URL index
- **WHEN** data is loaded
- **THEN** URL index maps URLs to PhishTankEntry objects

#### Scenario: Domain index
- **WHEN** data is loaded
- **THEN** domain index maps domains to sets of phishing URLs

### Requirement: Error handling
The system SHALL handle sync failures gracefully.

#### Scenario: Download failure
- **WHEN** PhishTank data download fails
- **THEN** existing local data remains available
- **AND** warning is logged

#### Scenario: Invalid data
- **WHEN** PhishTank data parsing fails
- **THEN** warning is logged
- **AND** individual entries are skipped