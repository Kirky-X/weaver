# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Fixed

#### Type Safety

- Fixed dataclass type annotations in `src/core/llm/types.py`: `list[str] = None` → `list[str] | None = None` for `RoutingConfig.fallbacks`, `ProviderConfig.models`, `GlobalConfig.defaults`, `GlobalConfig.call_points`
- Fixed `sanitize_dict` return type annotation in `src/core/utils/sanitize.py`: `dict[str, str]` → `dict[str, Any]`
- Fixed variable name conflict in `src/modules/migration/mapping_registry.py` causing type inference errors

#### Security

- Removed hardcoded default password `"neo4j_password"` from `Neo4jSettings` in `src/config/settings.py`
- Updated `.env.example` with clear security configuration instructions

#### Code Quality

- Added debug logging to silent exception handlers in `src/modules/processing/pipeline/graph.py`

### Verified

- All 856 tests pass
- mypy type checking passes for modified files
- ruff lint checks pass
- No new hardcoded secrets detected
