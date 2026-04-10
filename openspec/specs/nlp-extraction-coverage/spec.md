## ADDED Requirements

### Requirement: Entity extraction with multiple entity types
The test suite SHALL verify extraction of different entity types (PERSON, ORG, GPE, etc.).

#### Scenario: Person entities are extracted correctly
- **WHEN** text contains person names
- **THEN** all person entities SHALL be extracted with correct offsets

#### Scenario: Organization entities are extracted correctly
- **WHEN** text contains organization names
- **THEN** all organization entities SHALL be extracted with correct types

#### Scenario: Location entities are extracted correctly
- **WHEN** text contains geographical names
- **THEN** all GPE entities SHALL be extracted with correct labels

### Requirement: Language detection and model selection
The test suite SHALL verify language-specific processing.

#### Scenario: English text uses English model
- **WHEN** input text is in English
- **THEN** the English SpaCy model SHALL be used for extraction

#### Scenario: Unsupported language falls back gracefully
- **WHEN** input text is in an unsupported language
- **THEN** the system SHALL either use a fallback model or return empty results

### Requirement: Edge cases in extraction
The test suite SHALL verify handling of edge cases.

#### Scenario: Empty text returns empty results
- **WHEN** input text is empty or whitespace
- **THEN** no entities SHALL be extracted

#### Scenario: Very long text is processed correctly
- **WHEN** input text exceeds typical document length
- **THEN** extraction SHALL complete without timeout or memory issues

#### Scenario: Special characters are handled properly
- **WHEN** text contains special Unicode characters
- **THEN** entity offsets SHALL be calculated correctly