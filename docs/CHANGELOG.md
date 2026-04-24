# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

#### LLM Configuration

- **LiveConfig Hot-Reload**: Integrated live configuration reload for LLM module, allowing `config/llm.toml` changes
  without service restart
    - Atomic configuration swap with validation
    - Automatic SmartRouter rebuild on config change
    - File watcher using `watchfiles` library

#### Search Capabilities

- **Explicit Search Mode**: Added `mode` parameter to search endpoint supporting `local`, `global`, and `auto` (default)
  modes
    - `local`: Direct vector search for entity neighborhoods
    - `global`: Community-level search with Map-Reduce pattern
    - `auto`: Intent-based automatic routing (existing behavior)

#### Community Detection

- **LLM-Powered Title Generation**: Automatic community title generation using LLM during community detection
    - Uses dedicated `community_title` call point
    - Configurable via `config/prompts/community_title.toml`
    - Titles limited to 10 characters, extracted from entity themes

#### Database & Storage

- **EXCITED Sentiment Type**: Added new sentiment type for emotion analysis in `AnalyzeOutput`
- **DuckDB Support**: Added DuckDB as database fallback with dedicated schema initialization
- **E2E Testing**: Docker-less fallback support for E2E tests, enabling testing without container runtime

### Changed

#### Architecture

- **Scripts Consolidation**: Merged `scripts` directory from 12 to 4 core scripts for better maintainability
- **Legacy Code Removal**: Removed backward compatibility code for cleaner codebase
- **Main Config Loading**: Replaced `toml` library with `tomllib` (Python 3.11+ standard library)

#### API & Endpoints

- **Health Check Simplification**: Simplified health check endpoint for load balancer compatibility
- **Community Report Fields**: Extended community report query with `key_entities`, `key_relationships`, and `rank`
  attributes
- **Public API**: Exposed `list_enabled_sources` as public API endpoint

#### Performance & Optimization

- **DuckDB Schema Initialization**: Optimized to single session mode for better performance
- **Tracing Configuration**: Enhanced tracing config to support empty endpoint disabling

### Deprecated

- **LangChain/LangGraph**: Removed from dependencies (replaced by LiteLLM integration)

### Removed

- **Legacy Compatibility Code**: Removed old backward compatibility layers
- **Hardcoded Default Password**: Removed `"neo4j_password"` default from `Neo4jSettings`

### Fixed

#### Type Safety

- Fixed dataclass type annotations in `src/core/llm/types.py`: `list[str] = None` → `list[str] | None = None` for
  `RoutingConfig.fallbacks`, `ProviderConfig.models`, `GlobalConfig.defaults`, `GlobalConfig.call_points`
- Fixed `sanitize_dict` return type annotation in `src/core/utils/sanitize.py`: `dict[str, str]` → `dict[str, Any]`
- Fixed variable name conflict in `src/modules/migration/mapping_registry.py` causing type inference errors

#### Security

- **BM25 Index Loading**: Added `RestrictedUnpickler` to prevent remote code execution when loading BM25 indices
    - Only allows safe built-in types (dict, list, tuple, str, int, etc.)
    - Blocks arbitrary class instantiation
- **Vector Similarity Queries**: Added input validation for vector similarity query parameters
- **SSRF Protection**: Enhanced SSRF protection with inline URL validation
- **Migration Adapters**: Fixed SQL injection vulnerabilities and added detailed logging
- **API Response Errors**: Made validation errors JSON-serializable in API responses

#### Bug Fixes

- **DuckDB Schema**: Fixed DuckDB schema initialization in container startup
- **Newsnow Parser**: Corrected list page detection for numeric IDs (e.g., 36kr URLs)
- **Community Repository**: Fixed community repo and Ladybug schema compatibility issues
- **Spacy Package**: Fixed spacy wheel package extraction logic
- **E2E Tests**: Fixed auth middleware settings retrieval and data validator logic
- **Health Check**: Fixed health check endpoint test assertions
- **Test Mocks**: Fixed test mock query count mismatch and configuration defaults

#### Code Quality

- Added debug logging to silent exception handlers in `src/modules/processing/pipeline/graph.py`
- Enhanced error handling with detailed logging across migration adapters and core modules

### Verified

- All 856 tests pass
- mypy type checking passes for modified files
- ruff lint checks pass
- No new hardcoded secrets detected
