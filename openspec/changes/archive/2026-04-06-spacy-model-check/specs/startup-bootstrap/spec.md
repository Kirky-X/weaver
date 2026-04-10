## ADDED Requirements

### Requirement: Early model validation
The application SHALL validate spaCy model availability immediately after Settings load and before container initialization.

#### Scenario: Settings loaded successfully
- **WHEN** Settings object is fully loaded
- **THEN** SpacyModelManager.check_and_install() is invoked

#### Scenario: Model validation passes
- **WHEN** all models are present or successfully installed
- **THEN** application continues to container initialization

#### Scenario: Model validation fails in strict mode
- **WHEN** model installation fails and strict_mode is true
- **THEN** application exits with error code and descriptive message

#### Scenario: Model validation fails in non-strict mode
- **WHEN** model installation fails and strict_mode is false
- **THEN** application logs warning and continues startup