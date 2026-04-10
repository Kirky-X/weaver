## ADDED Requirements

### Requirement: List all active prompts

The system SHALL provide an API endpoint to list all active prompt templates.

#### Scenario: List all prompts
- **WHEN** GET `/admin/prompts` is called with valid API key
- **THEN** the system SHALL return a list of all prompts with `is_active = TRUE`

#### Scenario: Response includes metadata
- **WHEN** listing prompts
- **THEN** each prompt entry SHALL include: `name`, `version`, `prompt_type`, `is_active`, `updated_at`

---

### Requirement: Get single prompt details

The system SHALL provide an API endpoint to get details of a specific prompt.

#### Scenario: Get existing prompt
- **WHEN** GET `/admin/prompts/{name}` is called for existing prompt "classifier"
- **THEN** the system SHALL return the active version's details including full `content`

#### Scenario: Prompt not found
- **WHEN** GET `/admin/prompts/{name}` is called for non-existent prompt
- **THEN** the system SHALL return 404 Not Found

---

### Requirement: Update prompt content

The system SHALL provide an API endpoint to update prompt content, automatically creating a new version.

#### Scenario: Update creates new version
- **WHEN** PUT `/admin/prompts/classifier` with `{"content": "new content", "reason": "improve accuracy"}`
- **THEN** the system SHALL create a new version with auto-incremented version number and `is_active = TRUE`

#### Scenario: Update deactivates previous version
- **WHEN** updating prompt "classifier"
- **THEN** the previous active version SHALL be set to `is_active = FALSE`

#### Scenario: Update requires authentication
- **WHEN** PUT `/admin/prompts/{name}` is called without valid API key
- **THEN** the system SHALL return 401 Unauthorized

---

### Requirement: List version history

The system SHALL provide an API endpoint to list all versions of a prompt.

#### Scenario: List all versions
- **WHEN** GET `/admin/prompts/{name}/versions` is called
- **THEN** the system SHALL return all versions ordered by `created_at` descending

#### Scenario: Version list includes metadata
- **WHEN** listing versions
- **THEN** each version entry SHALL include: `id`, `version`, `is_active`, `change_reason`, `created_at`, `created_by`

---

### Requirement: Activate specific version (rollback)

The system SHALL provide an API endpoint to activate a specific version.

#### Scenario: Activate older version
- **WHEN** POST `/admin/prompts/classifier/activate` with `{"version": "1.0.0", "reason": "rollback"}`
- **THEN** the system SHALL set `is_active = TRUE` for version "1.0.0" and `is_active = FALSE` for all other versions

#### Scenario: Version not found
- **WHEN** activating non-existent version "99.0.0"
- **THEN** the system SHALL return 404 Not Found

---

### Requirement: Hot reload prompt cache

The system SHALL provide API endpoints to reload prompt cache from database.

#### Scenario: Reload single prompt cache
- **WHEN** POST `/admin/prompts/{name}/reload` is called
- **THEN** the system SHALL clear all cached entries for that prompt

#### Scenario: Reload all prompts cache
- **WHEN** POST `/admin/prompts/reload` is called
- **THEN** the system SHALL clear all cached prompts

---

### Requirement: Import prompts from TOML file

The system SHALL provide an API endpoint to import prompts from uploaded TOML files.

#### Scenario: Upload single TOML file
- **WHEN** POST `/admin/prompts/import` with TOML file `classifier.toml`
- **THEN** the system SHALL parse the file, create/insert prompt template, and return import result

#### Scenario: Upload multiple TOML files
- **WHEN** POST `/admin/prompts/import` with multiple TOML files
- **THEN** the system SHALL process all files and return summary with `imported`, `skipped`, `errors` lists

#### Scenario: Skip existing with overwrite=false
- **WHEN** importing "classifier.toml" that already exists with `overwrite=false`
- **THEN** the system SHALL skip it and add to `skipped` list

#### Scenario: Overwrite existing with overwrite=true
- **WHEN** importing "classifier.toml" that already exists with `overwrite=true`
- **THEN** the system SHALL create a new version of the existing prompt

---

### Requirement: Export prompts

The system SHALL provide API endpoints to export prompts to TOML format.

#### Scenario: Export single prompt
- **WHEN** GET `/admin/prompts/{name}/export` is called
- **THEN** the system SHALL return the active version as a TOML file with `application/toml` content type

#### Scenario: Export all prompts as ZIP
- **WHEN** GET `/admin/prompts/export` is called
- **THEN** the system SHALL return a ZIP file containing all active prompts as individual TOML files

---

### Requirement: All endpoints require API key authentication

The system SHALL require valid API key authentication for all `/admin/prompts/*` endpoints.

#### Scenario: Missing API key
- **WHEN** any `/admin/prompts/*` endpoint is called without API key
- **THEN** the system SHALL return 401 Unauthorized

#### Scenario: Invalid API key
- **WHEN** any `/admin/prompts/*` endpoint is called with invalid API key
- **THEN** the system SHALL return 401 Unauthorized