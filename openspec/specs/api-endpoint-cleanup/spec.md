## ADDED Requirements

### Requirement: Fix `/api/v1/config` runtime bug

The `/api/v1/config` endpoint in `main.py` MUST call existing `Endpoints` methods. It currently references `get_llm_client()`, `get_local_search_engine()`, and `get_graph_pool()` which do not exist. The correct methods are `get_llm()`, `get_local_engine()`, and `get_graph_pool_optional()`.

#### Scenario: `/api/v1/config` returns valid configuration
- **WHEN** user calls `GET /api/v1/config`
- **THEN** endpoint returns 200 with `relational_pool_type`, `graph_pool_type`, `llm_enabled`, `search_enabled`, `graph_available` fields without raising `AttributeError`

### Requirement: Remove migration API from public surface

The `/api/v1/migration` router MUST be removed from `api/router.py`. The internal migration module (`modules/migration/`) remains intact but is no longer exposed via HTTP.

#### Scenario: Migration endpoints return 404
- **WHEN** user calls `POST /api/v1/migration/relational`
- **THEN** returns 404 Not Found

### Requirement: Merge community routers

Community list and detail endpoints currently at `/api/v1/graph/communities` MUST be merged into the `/api/v1/admin/communities` router. The old paths MUST return 301 redirects to the new paths.

#### Scenario: List communities at unified path
- **WHEN** user calls `GET /api/v1/admin/communities`
- **THEN** returns paginated community list

#### Scenario: Get community detail at unified path
- **WHEN** user calls `GET /api/v1/admin/communities/{community_id}`
- **THEN** returns community detail with entities and report

#### Scenario: Old `/graph/communities` path redirects
- **WHEN** user calls `GET /api/v1/graph/communities`
- **THEN** returns 301 with `Location: /api/v1/admin/communities`

### Requirement: Consolidate LLM usage endpoints

The 5 LLM usage endpoints under `/api/v1/admin/llm-usage*` MUST be consolidated into a single `GET /api/v1/admin/llm-usage` endpoint with a `group_by` query parameter. Old endpoints MUST be kept with deprecation warnings for one release cycle.

#### Scenario: Time-grouped usage (replaces old `/llm-usage`)
- **WHEN** user calls `GET /api/v1/admin/llm-usage?group_by=time&from=...&to=...`
- **THEN** returns time-bucketed usage records (same data as old `/llm-usage`)

#### Scenario: Summary usage (replaces old `/llm-usage/summary`)
- **WHEN** user calls `GET /api/v1/admin/llm-usage?group_by=summary&from=...&to=...`
- **THEN** returns aggregate statistics (total calls, tokens, latency, success rate)

#### Scenario: Provider-grouped usage (replaces old `/llm-usage/by-provider`)
- **WHEN** user calls `GET /api/v1/admin/llm-usage?group_by=provider&from=...&to=...`
- **THEN** returns usage grouped by LLM provider

#### Scenario: Model-grouped usage (replaces old `/llm-usage/by-model`)
- **WHEN** user calls `GET /api/v1/admin/llm-usage?group_by=model&from=...&to=...`
- **THEN** returns usage grouped by model name

#### Scenario: Call-point-grouped usage (replaces old `/llm-usage/by-call-point`)
- **WHEN** user calls `GET /api/v1/admin/llm-usage?group_by=call_point&from=...&to=...`
- **THEN** returns usage grouped by call point

#### Scenario: Deprecated endpoints still work
- **WHEN** user calls `GET /api/v1/admin/llm-usage/by-provider`
- **THEN** returns same response as before, with `Deprecation` header

### Requirement: Remove duplicate article graph endpoint

The `GET /api/v1/graph/articles/{article_id}` endpoint (graph.py:155) MUST be removed. Its functionality (returning article node data) is already provided by `GET /api/v1/articles/{article_id}` (articles.py:208) and `GET /api/v1/graph/articles/{article_id}/graph` (graph.py:178).

#### Scenario: Lightweight article endpoint returns 404
- **WHEN** user calls `GET /api/v1/graph/articles/{article_id}` (the graph-info variant)
- **THEN** returns 404 Not Found

#### Scenario: Full article graph endpoint still works
- **WHEN** user calls `GET /api/v1/graph/articles/{article_id}/graph`
- **THEN** returns article node, entities, relationships, and related articles

### Requirement: Remove duplicate ArticleGraphResponse class

The `ArticleGraphResponse` class defined at graph.py:146 MUST be removed. The class at graph.py:71-77 SHALL be the single definition. All handlers MUST use the shared type.

#### Scenario: No duplicate class definitions
- **WHEN** running `grep -c "class ArticleGraphResponse" src/api/endpoints/graph.py`
- **THEN** returns count of 1

## REMOVED Requirements

### Requirement: Migration API endpoints
**Reason**: One-time data migration tools should not be exposed as production API endpoints. Internal migration logic remains in `modules/migration/`.
**Migration**: If needed during active migration, run migration via CLI or direct module invocation.

### Requirement: Deprecated search parameters
**Reason**: The `mode`, `entity_names`, and `max_tokens` query parameters on `GET /api/v1/search` are deprecated in favor of intent-based routing.
**Migration**: Use automatic intent routing. Remove `mode`, `entity_names`, `max_tokens` parameters from client requests.
