## Why

The API surface has grown organically to ~46 endpoints across 10 modules, introducing several classes of technical debt:

1. **Bug**: `/api/v1/config` references methods that don't exist on `Endpoints` (`get_llm_client`, `get_local_search_engine`), causing runtime `AttributeError`.
2. **Redundancy**: Community management is split across two routers (`/admin/communities` for operations, `/graph/communities` for queries). LLM usage analytics has 5 nearly-identical endpoints that differ only by `GROUP BY` clause.
3. **Stale endpoints**: The `/api/v1/migration` module provides 6 one-time data migration endpoints that shouldn't be exposed in production APIs.
4. **Overlapping health scoring**: Community health is independently computed in three places (`/admin/communities/health`, `/admin/communities/health/diagnose`, `/graph/metrics?view=community`), risking inconsistent results.

## What Changes

- **FIX**: Repair `/api/v1/config` to call existing `Endpoints` methods
- **MERGE**: Collapse `/graph/communities` into `/admin/communities` under unified prefix
- **MERGE**: Consolidate 5 LLM usage endpoints into one with `group_by` query parameter
- **REMOVE**: Delete `/api/v1/migration` API (move to CLI tooling if still needed)
- **REMOVE**: Remove `/graph/articles/{article_id}` (fully subsumed by `{article_id}/graph`)
- **FIX**: Remove duplicate `ArticleGraphResponse` class definition in `graph.py`
- **DEPRECATE**: Mark deprecated search parameters for future removal

## Capabilities

### New Capabilities
- `api-endpoint-cleanup`: Consolidation, removal, and bug fixes for existing API endpoints

### Modified Capabilities
- `search-api-tests`: Deprecated parameter removal affects search endpoint contract
- `graph-metrics-api-tests`: Community view removal from graph metrics affects test scope

## Impact

- **src/api/endpoints/graph.py**: Remove duplicate class, remove `/articles/{article_id}` endpoint
- **src/api/endpoints/communities.py**: Merge two routers, unify health scoring
- **src/api/endpoints/admin.py**: Merge LLM usage endpoints
- **src/api/router.py**: Remove migration router, update community router registration
- **src/modules/migration/api/routes.py**: Entire file targeted for removal
- **src/main.py**: Fix `/api/v1/config` endpoint
- **tests/**: Update tests for removed/merged endpoints
