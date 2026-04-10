## ADDED Requirements

### Requirement: Prompt templates are stored in database

The system SHALL store prompt templates in the `prompt_templates` database table with the following fields: `name`, `version`, `prompt_type`, `content`, `is_active`, `change_reason`, `metadata`, `created_at`, `updated_at`, `created_by`.

#### Scenario: Store a new prompt template
- **WHEN** a prompt template is created with name "classifier", version "1.0.0", prompt_type "system", and content "..."
- **THEN** the system SHALL insert a new row into `prompt_templates` table with `is_active = TRUE`

#### Scenario: Unique name-version constraint
- **WHEN** attempting to insert a prompt with name "classifier" and version "1.0.0" that already exists
- **THEN** the system SHALL reject the insert with a unique constraint violation error

---

### Requirement: Multiple versions of same prompt can coexist

The system SHALL allow multiple versions of the same prompt name to exist in the database, with exactly one version marked as active (`is_active = TRUE`) at any time.

#### Scenario: Create new version deactivates previous
- **WHEN** a new version "1.1.0" is created for prompt "classifier" while "1.0.0" is active
- **THEN** the system SHALL set `is_active = FALSE` for version "1.0.0" and `is_active = TRUE` for version "1.1.0"

#### Scenario: Only one active version per prompt
- **WHEN** querying active prompts
- **THEN** the system SHALL return at most one version per prompt name

---

### Requirement: Version rollback is supported

The system SHALL support activating a historical version of a prompt, effectively rolling back to that version.

#### Scenario: Rollback to previous version
- **WHEN** activating version "1.0.0" for prompt "classifier" while "1.1.0" is active
- **THEN** the system SHALL set `is_active = FALSE` for "1.1.0" and `is_active = TRUE` for "1.0.0"

#### Scenario: Rollback with reason
- **WHEN** rolling back to version "1.0.0" with reason "Bug in 1.1.0 classification logic"
- **THEN** the system SHALL record the reason for auditing purposes

---

### Requirement: Initial data is imported on first startup

The system SHALL automatically import prompt templates from `config/prompts/*.toml` directory when the database has no prompt records, then delete the directory.

#### Scenario: Import on empty database
- **WHEN** the application starts and `prompt_templates` table is empty
- **THEN** the system SHALL scan `config/prompts/` directory, parse all TOML files, insert them into the database, and delete the `config/prompts/` directory

#### Scenario: Skip import when prompts exist
- **WHEN** the application starts and `prompt_templates` table already has records
- **THEN** the system SHALL skip the import process

#### Scenario: Import failure does not delete directory
- **WHEN** import from `config/prompts/` fails due to parsing error
- **THEN** the system SHALL NOT delete the directory and SHALL log the error

---

### Requirement: Version numbers follow semantic versioning

The system SHALL automatically generate new version numbers following semantic versioning, incrementing the PATCH level.

#### Scenario: Auto-increment patch version
- **WHEN** updating prompt "classifier" with current version "1.2.0"
- **THEN** the system SHALL create new version "1.2.1"

#### Scenario: Version from scratch
- **WHEN** creating a new prompt "new-prompt" with no existing versions
- **THEN** the system SHALL use version "1.0.0"

---

### Requirement: Old versions are automatically cleaned up

The system SHALL automatically delete old versions beyond the configured `max_history_versions` limit (default 10).

#### Scenario: Cleanup excess versions
- **WHEN** prompt "classifier" has 12 versions and `max_history_versions = 10`
- **THEN** the system SHALL delete the 2 oldest inactive versions

#### Scenario: Never delete active version
- **WHEN** cleaning up old versions
- **THEN** the system SHALL never delete the currently active version regardless of age