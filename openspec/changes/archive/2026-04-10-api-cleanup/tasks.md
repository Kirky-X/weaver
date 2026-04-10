## 1. Fix `/api/v1/config` runtime bug

- [x] 1.1 Update `main.py:419` — replace `Endpoints.get_llm_client()` with `Endpoints._llm` None check
- [x] 1.2 Update `main.py:420` — replace `Endpoints.get_local_search_engine()` with `Endpoints._local_engine` None check
- [x] 1.3 Update `main.py:421` — replace `Endpoints.get_graph_pool()` with `Endpoints._graph_pool` None check
- [x] 1.4 Add test for `/api/v1/config` endpoint in test_api.py

## 2. Remove duplicate `ArticleGraphResponse` class

- [x] 2.1 Remove duplicate `ArticleGraphResponse` at `graph.py:146` (already done in prior session)
- [x] 2.2 Handler already uses shared class

## 3. Remove `/graph/articles/{article_id}` endpoint

- [x] 3.1 Remove the `get_article_graph_info` endpoint (already done in prior session)
- [x] 3.2 `ArticleGraphNode` still used by remaining endpoint
- [x] 3.3 No tests referenced the removed endpoint directly

## 4. Remove migration API router

- [x] 4.1 Remove `migration_router` import and `include_router` call from `api/router.py`
- [x] 4.2 Verified no other modules import from `modules.migration/api/` (only internal migration code)
- [x] 4.3 No tests depend on migration endpoints

## 5. Consolidate community routers

- [x] 5.1 Moved `list_communities` and `get_community` handlers into main `router` in `communities.py`
- [x] 5.2 Removed `graph_router` from `communities.py`
- [x] 5.3 Removed `communities.graph_router` include from `api/router.py`
- [x] 5.4 Added `_redirect_router` with 301 redirect at `/graph/communities`
- [x] 5.5 Updated tests for community endpoints

## 6. Consolidate LLM usage endpoints

- [x] 6.1 Created unified `GET /api/v1/admin/llm-usage` handler with `group_by` parameter
- [x] 6.2 Implemented inline logic for all 5 dimensions in single handler
- [x] 6.3 Added `deprecated=True` to old endpoints (`/llm-usage/time`, `/llm-usage/summary`, `/by-provider`, `/by-model`, `/by-call-point`)
- [x] 6.4 Tests updated for graph metrics (community view removal)
- [x] 6.5 Deprecation markers via FastAPI's `deprecated=True` flag

## 7. Update graph metrics community view

- [x] 7.1 Removed `_get_community_view` function from `graph_metrics.py`
- [x] 7.2 Returns 400 for `view=community` with message pointing to `/admin/communities/health`
- [x] 7.3 Updated tests — changed to expect 400, removed dead model tests

## 8. Final verification

- [x] 8.1 Ran test suite — 27/27 pass for affected test files (search_api.py has pre-existing failure unrelated to this change)
- [x] 8.2 Linting clean (`uv run ruff check src/` — 0 errors)
- [x] 8.3 Verified no dead imports remain
- [x] 8.4 Ran `gitnexus_detect_changes` — confirmed expected scope (16 files changed, 90 affected symbols)
