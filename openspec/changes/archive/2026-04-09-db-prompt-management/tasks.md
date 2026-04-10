## 1. Database Model & Migration

- [x] 1.1 Add `PromptTemplate` ORM model to `src/core/db/models.py` with fields: id, name, version, prompt_type, content, is_active, change_reason, metadata, created_at, updated_at, created_by
- [x] 1.2 Add unique constraint `uq_prompt_name_version` on (name, version)
- [x] 1.3 Create Alembic migration for `prompt_templates` table
- [x] 1.4 Run migration and verify table creation

## 2. Prompt Repository

- [x] 2.1 Create `src/core/prompt/repo.py` with `PromptRepository` class
- [x] 2.2 Implement `get_active(name)` - fetch active version by name
- [x] 2.3 Implement `get_by_name_version(name, version)` - fetch specific version
- [x] 2.4 Implement `get_all_versions(name)` - list all versions for a prompt
- [x] 2.5 Implement `list_all_active()` - list all active prompts
- [x] 2.6 Implement `count_prompts()` - count total prompts
- [x] 2.7 Implement `insert(prompt)` - create new prompt version
- [x] 2.8 Implement `batch_insert(prompts)` - batch create prompts
- [x] 2.9 Implement `update_content(name, content, reason, by)` - update and create new version
- [x] 2.10 Implement `activate_version(name, version, reason)` - activate specific version
- [x] 2.11 Implement `cleanup_old_versions(name, keep)` - delete old versions

## 3. Prompt Cache

- [x] 3.1 Create `src/core/prompt/cache.py` with `PromptCache` class
- [x] 3.2 Implement `__init__(cache: CachePool, ttl: int, enabled: bool)`
- [x] 3.3 Implement `get(name, prompt_type)` - get cached content
- [x] 3.4 Implement `set(name, prompt_type, content)` - cache content
- [x] 3.5 Implement `delete(name, prompt_type)` - invalidate single cache entry
- [x] 3.6 Implement `delete_all(name)` - invalidate all cache for a prompt
- [x] 3.7 Implement `clear()` - clear all prompt caches

## 4. DbPromptLoader

- [x] 4.1 Create `src/core/prompt/db_loader.py` with `DbPromptLoader` class
- [x] 4.2 Implement `__init__(repo, cache, settings)` with dependency injection
- [x] 4.3 Implement `get(name, key="system")` - get prompt with cache-first strategy
- [x] 4.4 Implement `get_version(name)` - get current active version
- [x] 4.5 Implement `reload(name=None)` - hot reload cache
- [x] 4.6 Implement `update_prompt(name, content, reason)` - update with auto-versioning
- [x] 4.7 Implement `activate_version(name, version, reason)` - version rollback
- [x] 4.8 Implement `get_versions(name)` - get version history
- [x] 4.9 Implement `import_from_toml(file_content, overwrite)` - parse TOML and import single prompt
- [x] 4.10 Implement `import_initial_data()` - startup import from `config/prompts/` and delete directory

## 5. Configuration

- [x] 5.1 Extend `PromptSettings` in `src/config/settings.py` with:
  - `cache_enabled: bool = True`
  - `cache_ttl_seconds: int = 3600`
  - `max_history_versions: int = 10`
  - `auto_cleanup_old_versions: bool = True`
  - `initial_data_path: str = "config/prompts"` - path for initial import

## 6. API Schemas

- [x] 6.1 Create `src/api/schemas/prompt.py` with:
  - `PromptResponse` - single prompt details
  - `PromptListItem` - list item with metadata
  - `PromptVersionResponse` - version history item
  - `UpdatePromptRequest` - update request body
  - `ActivateVersionRequest` - activate version request
  - `ImportPromptsResponse` - import result

## 7. API Endpoints

- [x] 7.1 Create `src/api/endpoints/prompts.py` with APIRouter
- [x] 7.2 Implement `GET /admin/prompts` - list all active prompts
- [x] 7.3 Implement `GET /admin/prompts/{name}` - get single prompt
- [x] 7.4 Implement `PUT /admin/prompts/{name}` - update prompt
- [x] 7.5 Implement `GET /admin/prompts/{name}/versions` - list version history
- [x] 7.6 Implement `POST /admin/prompts/{name}/activate` - activate version
- [x] 7.7 Implement `POST /admin/prompts/{name}/reload` - reload single prompt cache
- [x] 7.8 Implement `POST /admin/prompts/reload` - reload all caches
- [x] 7.9 Implement `POST /admin/prompts/import` - upload TOML files (multipart/form-data)
- [x] 7.10 Implement `GET /admin/prompts/export` - export all as ZIP
- [x] 7.11 Implement `GET /admin/prompts/{name}/export` - export single as TOML

## 8. Container Integration

- [x] 8.1 Update `src/container.py` `prompt_loader()` to use `DbPromptLoader`
- [x] 8.2 Register prompts router in `src/api/endpoints/__init__.py`
- [x] 8.3 Update `src/core/prompt/__init__.py` to export `DbPromptLoader`

## 9. Remove Old Implementation

- [x] 9.1 Delete `src/core/prompt/loader.py` (old file system loader)
- [x] 9.2 Remove `PromptLoader` imports from all files
- [x] 9.3 Update `src/core/llm/client.py` type hints to use `DbPromptLoader`
- [x] 9.4 Remove `config/prompts/` directory after initial import (done in startup)

## 10. Testing

- [x] 10.1 Create `tests/unit/core/prompt/test_repo.py` - repository unit tests
- [x] 10.2 Create `tests/unit/core/prompt/test_cache.py` - cache unit tests
- [x] 10.3 Create `tests/unit/core/prompt/test_db_loader.py` - loader unit tests
- [x] 10.4 Create `tests/unit/api/test_prompts_api.py` - API endpoint tests

## 11. Documentation

- [x] 11.1 Update `docs/CHANGELOG.md` with new feature
- [x] 11.2 Update `README.md` with prompt management documentation