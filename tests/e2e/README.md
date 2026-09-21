# E2E Tests for Weaver

End-to-end tests exercise the complete application stack through the HTTP API: real FastAPI app, real databases
(DuckDB/LadybugDB fallback by default, optional Docker full stack).

## Running E2E Tests

```bash
# Standard run (DuckDB/LadybugDB fallback, no Docker required, single process)
uv run pytest tests/e2e -m e2e -n 0 --no-cov

# Docker full-stack mode (PostgreSQL + Neo4j + Redis, opt-in)
WEAVER_E2E_USE_DOCKER=1 uv run pytest tests/e2e -m e2e -n 0 --no-cov
```

Key constraints:

- **`-n 0` (single process) is mandatory**: the fallback databases are single-writer
  files; pytest-xdist workers crash with an OS file-lock error. The suite fails fast
  with guidance when it detects an xdist worker.
- **`--no-cov` is expected**: the project-wide 80% coverage gate applies to the full
  unit suite; a standalone E2E run does not reach it.
- **Docker mode is opt-in** via `WEAVER_E2E_USE_DOCKER=1` so results do not depend on
  a local Docker daemon being up.
- Skips are always explicit (Ollama unavailable, public feed unreachable, empty
  database) — never silent.

### Docker services (opt-in mode)

| Service    | Port       | Image                  |
|------------|------------|------------------------|
| PostgreSQL | 5433       | pgvector/pgvector:pg16 |
| Neo4j      | 7475, 7688 | neo4j:5.25             |
| Redis      | 6380       | redis:7-alpine         |

## Suite Structure

```
tests/e2e/
├── conftest.py               # Session fixtures (client, auth, audit recorder, docker opt-in)
├── api_response_recorder.py  # Per-request JSON audit records
├── reporting.py              # Markdown audit report generator
├── data_validator.py         # Cross-validation against source databases
├── test_env.env              # Test environment (keys, DB paths, INDEX_SIGNING_KEY)
├── docker-compose.yml        # Isolated full-stack environment (opt-in)
├── endpoints/                # Per-domain endpoint suites (all 82 API endpoints)
│   ├── _kit.py               # Shared helpers: strict envelope assertions + audit
│   ├── test_system.py        # /health, /metrics, status, config, cache, reload
│   ├── test_sources.py       # Source CRUD + bounds + SSRF blacklist
│   ├── test_articles.py      # List (pagination/filters/enum) + detail
│   ├── test_pipeline.py      # trigger / task status / queue / URL / SSE
│   ├── test_search.py        # unified + local/global/drift/causal/temporal
│   ├── test_graph.py         # entities / relations / traverse / metrics / viz
│   ├── test_admin.py         # api-keys lifecycle, dedup, authorities, db monitoring
│   ├── test_monitoring.py    # alerts CRUD/trigger/cooldown, causal, LLM usage
│   ├── test_communities.py   # list / health / diagnose / repair / rebuild
│   ├── test_saga.py          # status / compensate / retry / failed list
│   └── test_analytics.py     # analytics, briefings, trends
├── flows/                    # Cross-endpoint user flows
└── pipeline/                 # Pipeline-level scenarios (4-phase, persistence)
```

## Assertion Contract

- **Exact status codes** — no loose `in [200, 400, 500]` allow-lists.
- **Unified envelope** `{code, message, data, timestamp}`; success `code == 0`
  (documented exceptions pinned by tests: missing briefing → `data: null`,
  saga endpoints return bare dicts).
- **Business code mapping**: 400→10001, 401→10002, 403→10003, 404→10004,
  409→10005, 422→10001, 503→50001, otherwise 10099.
- **Environment-dependent endpoints** (LLM/graph-backed) use `api_call_multi`
  to assert a strict contract per acceptable status (e.g. 200 full stack vs
  503 fallback); the audit record shows which branch was taken.
- **Fault-tolerance paths are first-class**: analytics degrade to 200 with empty
  lists, trends report `insufficient_data`, graph visualization surfaces
  `metadata.error` — each has a dedicated test.

## Audit Records & Report

Every request is recorded for human review:

- Per-request JSON: `temp/api_responses/<domain>/<scenario>_<timestamp>.json`
- Aggregate stats: `temp/api_responses/summary.json`
- **Audit report**: `temp/api_audit_report.md` — generated automatically at session
  teardown (overview, status distribution, per-scenario table with method/path/
  params/status/business code/duration/assertion outcome)

## Fixtures

| Fixture          | Scope    | Description                              |
|------------------|----------|------------------------------------------|
| `docker_compose` | session  | Starts/stops Docker services (opt-in)    |
| `db_migrations`  | session  | Runs Alembic migrations (Docker mode)    |
| `e2e_app`        | session  | Creates FastAPI app                      |
| `client`         | session  | TestClient for API calls                 |
| `recorder`       | session  | API audit recorder + report generation   |
| `auth_headers`   | function | Regular API key headers                  |
| `admin_headers`  | function | Admin API key headers                    |
| `unique_id`      | function | Unique ID for test isolation             |

## Markers

- `@pytest.mark.e2e` — marks a test as an E2E test
- E2E tests are excluded from the default test run (use `-m e2e` to include)
