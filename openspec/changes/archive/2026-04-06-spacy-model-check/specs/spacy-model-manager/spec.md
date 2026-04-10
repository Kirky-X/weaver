## ADDED Requirements

### Requirement: Model presence detection
The system SHALL detect whether configured spaCy models are installed at startup time.

#### Scenario: All models present
- **WHEN** all configured models are installed
- **THEN** system logs success and continues startup

#### Scenario: Some models missing
- **WHEN** one or more configured models are not installed
- **THEN** system logs warning with list of missing models

### Requirement: Automatic model installation
The system SHALL support automatic installation of missing models when `force_install` is enabled.

#### Scenario: Force install enabled and models missing
- **WHEN** `force_install = true` and models are missing
- **THEN** system attempts to install each missing model serially

#### Scenario: Installation from local wheel
- **WHEN** `local_paths[model]` is configured and file exists
- **THEN** system installs model from local wheel file using uv

#### Scenario: Installation from network
- **WHEN** `local_paths[model]` is not configured or file does not exist
- **THEN** system downloads model using `spacy.cli.download()`

### Requirement: Installation failure handling
The system SHALL handle installation failures according to `strict_mode` setting.

#### Scenario: Strict mode enabled and installation fails
- **WHEN** `strict_mode = true` and model installation fails
- **THEN** system raises RuntimeError and application startup fails

#### Scenario: Strict mode disabled and installation fails
- **WHEN** `strict_mode = false` and model installation fails
- **THEN** system logs error and continues startup

### Requirement: Configuration support
The system SHALL support configuration of model list and installation behavior.

#### Scenario: Custom model list
- **WHEN** `models` is configured with custom list
- **THEN** system checks only those models

#### Scenario: Default model list
- **WHEN** `models` is not configured
- **THEN** system uses default list: ["zh_core_web_lg", "en_core_web_sm"]