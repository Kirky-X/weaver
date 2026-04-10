## Context

Weaver has ~46 API endpoints across 10 modules under `src/api/endpoints/`. The API grew incrementally as features were added, without systematic review of the overall surface. The current state has:

- **Two dependency registry patterns**: `api/dependencies.py` (thin wrappers) and `api/endpoints/_deps.py` (central `Endpoints` class). Both are kept in sync but the `main.py` config endpoint calls non-existent methods.
- **Community endpoints split** across `communities.py` (two routers: `/admin/communities` and `/graph/communities`).
- **LLM usage analytics** has 5 endpoints (`/llm-usage`, `/llm-usage/summary`, `/llm-usage/by-provider`, `/llm-usage/by-model`, `/llm-usage/by-call-point`) that differ only in SQL `GROUP BY`.
- **Migration module** exposes 6 one-time-use endpoints at runtime.
- **`graph.py`** has a duplicated `ArticleGraphResponse` class (line 71 and line 146).

## Goals / Non-Goals

**Goals:**
- Fix the runtime bug in `/api/v1/config`
- Reduce endpoint count by removing redundant, deprecated, and one-time-use endpoints
- Consolidate community management into a single router
- Consolidate LLM usage analytics into a parameterized endpoint
- Remove the duplicate class definition in `graph.py`
- Maintain backward compatibility where clients may depend on existing endpoints (use deprecation warnings, not silent breaks)

**Non-Goals:**
- Do NOT redesign the API from scratch (no version bump, no path restructuring beyond what's needed for consolidation)
- Do NOT change the Protocol-based dependency injection pattern
- Do NOT modify the migration module's internal logic (only remove its API exposure)

## Decisions

### D1: LLM Usage Endpoint Consolidation

**Decision**: Replace 5 endpoints with `GET /api/v1/admin/llm-usage?group_by=<dimension>` where `group_by ∈ {time, summary, provider, model, call_point}`.

**Rationale**: All 5 endpoints share the same `from`/`to` time range parameters and call the same repo layer. A single endpoint with a `group_by` parameter eliminates code duplication while preserving the same query semantics.

**Alternative considered**: Keep separate endpoints but share internal helper functions. Rejected because the endpoint definitions themselves are mostly boilerplate — the real duplication is in the route registration, parameter binding, and response wrapping.

**Backward compatibility**: The existing endpoints will be kept with `@deprecated` decorators for one release cycle before removal.

### D2: Community Router Merger

**Decision**: Merge `/graph/communities` (list + detail) into `/admin/communities` router. The unified router keeps prefix `/admin/communities`.

**Rationale**: "admin" is already where operations live. The `/graph/communities` prefix was an accident of implementation history, not intentional design. Merging into `/admin/communities` keeps all community operations under one namespace.

**Backward compatibility**: `/graph/communities` endpoints will return `301 Moved Permanently` with `Location` header pointing to the new paths.

### D3: Migration API Removal

**Decision**: Remove `/api/v1/migration` router entirely from `api/router.py`. The `modules/migration/` directory and its internal logic remain untouched — only the HTTP exposure is removed.

**Rationale**: Migration endpoints are one-time operational tools, not product APIs. They should be CLI commands or scripts, not exposed through the public API surface.

**Risk**: If someone is actively using these endpoints mid-migration, they'll break. **Mitigation**: Announce deprecation before merge.

### D4: Graph Article Endpoint Dedup

**Decision**: Remove `GET /api/v1/graph/articles/{article_id}` (line 155). The `/articles/{article_id}/graph` endpoint at line 178 already returns the article node plus full graph context.

**Rationale**: The lightweight endpoint serves no clear use case that the full endpoint doesn't also cover. If a lightweight "get article title/source" endpoint is needed later, it can be added as `GET /api/v1/articles/{article_id}/summary` — but currently `/api/v1/articles/{article_id}` already serves this purpose.

### D5: Duplicate ArticleGraphResponse Fix

**Decision**: Remove the second `ArticleGraphResponse` definition (line 146), keep the first one (line 71). Update the `get_article_graph_info` handler (line 155) to use the shared type.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| External clients depend on `/graph/communities` paths | 301 redirects preserve functionality |
| Migration team still needs API access during active migration | Communicate removal date; provide CLI alternative |
| LLM usage `group_by` parameter change breaks existing integrations | Deprecate old endpoints first, keep both for one cycle |
| Accidentally removing endpoints that ARE in use | Git grep for client-side references before merge |

## Migration Plan

1. Fix `/api/v1/config` bug (no migration needed, pure fix)
2. Add deprecation warnings to old LLM usage endpoints and `/graph/communities`
3. Add new consolidated endpoints alongside deprecated ones
4. Remove migration router and duplicate class definition
5. After one release cycle, remove deprecated endpoints entirely

## Open Questions

- Is the migration module still actively used? If yes, D3 should be deferred until a CLI alternative exists.
- Should the community health scoring logic be unified into a single shared function instead of having independent implementations?
