# Implementation Tasks

## 1. Type Annotation Fixes

### 1.1 Core LLM Types

- [x] 1.1.1 Fix `RoutingConfig.fallbacks` type annotation in `src/core/llm/types.py:135`
- [x] 1.1.2 Fix `ProviderConfig.models` type annotation in `src/core/llm/types.py:174`
- [x] 1.1.3 Fix `GlobalConfig.defaults` type annotation in `src/core/llm/types.py:192`
- [x] 1.1.4 Fix `GlobalConfig.call_points` type annotation in `src/core/llm/types.py:193`
- [x] 1.1.5 Run `mypy src/core/llm/types.py --ignore-missing-imports` to verify

### 1.2 Core Utils

- [x] 1.2.1 Fix `sanitize_dict` return type annotation in `src/core/utils/sanitize.py:88`
- [x] 1.2.2 Run `mypy src/core/utils/sanitize.py --ignore-missing-imports` to verify

### 1.3 Migration Registry

- [x] 1.3.1 Fix `mapping_registry.py` variable type annotations (renamed `mapping` to `rel_mapping` to avoid type conflict)

## 2. Security Hardening

### 2.1 Remove Hardcoded Defaults

- [x] 2.1.1 Change `Neo4jSettings.password` default from `"neo4j_password"` to `""` in `src/config/settings.py:81`
- [x] 2.1.2 Update `.env.example` with clear instructions for NEO4J_PASSWORD
- [x] 2.1.3 Run `uv run pytest tests/unit/config/` to verify settings (15 passed)

### 2.2 Security Configuration Validation

- [x] 2.2.1 Verify existing security validation in `settings.py:796-802` covers Neo4j password
- [x] 2.2.2 Startup warning for insecure defaults already exists (line 802)

## 3. Exception Handling Improvements

### 3.1 Critical Path Exception Handlers

- [x] 3.1.1 `src/container.py:773,785,822` - Already have proper logging with `log.warning()`
- [x] 3.1.2 `src/modules/knowledge/graph/incremental_community_updater.py:217,237,248,297` - Acceptable fallback for statistics queries
- [x] 3.1.3 `src/modules/processing/pipeline/graph.py:485,510,637,668` - Added debug logging for cleanup errors

### 3.2 Migration Adapters Exception Handlers

- [x] 3.2.1 `neo4j_target.py` - Already has comment explaining intent, acceptable as-is
- [x] 3.2.2 `ladybug_target.py` - Already has comment explaining intent, acceptable as-is
- [x] 3.2.3 `postgres_target.py` - Already has comments explaining intent, acceptable as-is

### 3.3 DuckDB Source/Target Exception Handlers

- [x] 3.3.1 `duckdb_source.py` - No silent exception handlers found
- [x] 3.3.2 `duckdb_target.py` - Has comments explaining intent, acceptable as-is

## 4. Verification

### 4.1 Type Safety

- [x] 4.1.1 Run `mypy src --ignore-missing-imports` - Fixed files pass, pre-existing errors remain in other files
- [x] 4.1.2 Run `uv run ruff check src` - All checks passed

### 4.2 Test Suite

- [x] 4.2.1 Run `uv run pytest tests/unit/config/` - 15 passed
- [x] 4.2.2 Run `uv run pytest tests/unit/core/` - Passed
- [x] 4.2.3 Run `uv run pytest tests/unit/api/middleware/` - Passed
- [x] 4.2.4 Run full test suite `uv run pytest tests/` - 856 passed

### 4.3 Security Verification

- [x] 4.3.1 Application starts correctly (verified via tests)
- [x] 4.3.2 Startup logs show security configuration status (existing validation)
- [x] 4.3.3 `detect-secrets` - No new hardcoded secrets introduced

## 5. Documentation

- [x] 5.1 Update CHANGELOG.md with changes
- [x] 5.2 Update `.env.example` with security configuration notes