# Docker Stacks for Weaver

Weaver ships three Docker Compose stacks covering production, primary test, and
cross-instance verification scenarios. All stacks use named volumes for
persistence and are designed to be mutually exclusive (run one at a time on a
given host to avoid port conflicts).

## Stacks

| File | Purpose | Backends | Ports |
|------|---------|----------|-------|
| `docker-compose.yml` | Production-style stack | PostgreSQL (pgvector) + Neo4j + Redis | 5432 / 7474 / 7687 / 6379 |
| `docker-compose.test.yml` | Primary test stack for API acceptance tests | pgvector/pgvector:pg16 + neo4j:5.25 + redis:7-alpine | 5432 / 7474 / 7687 / 6379 |
| `docker-compose.verify.yml` | Second instance for cross-instance data consistency verification | postgres (5433) + neo4j (7688); Redis reused from test stack | 5433 / 7475 / 7688 |

## Common Commands

```bash
# Start primary test stack
docker compose -f docker/docker-compose.test.yml up -d

# Wait for services to be healthy (Neo4j ~30s)
docker compose -f docker/docker-compose.test.yml ps

# Tear down primary test stack (keeps volumes)
docker compose -f docker/docker-compose.test.yml down

# Tear down and delete volumes (full reset)
docker compose -f docker/docker-compose.test.yml down -v
```

The same commands apply to `docker-compose.verify.yml` and `docker-compose.yml`
by swapping the `-f` argument.

## Service Credentials

Test and verify stacks use deterministic credentials for CI:

- PostgreSQL: `POSTGRES_USER=postgres`, `POSTGRES_PASSWORD=weavertest`,
  `POSTGRES_DB=weaver`
- Neo4j: `NEO4J_AUTH=neo4j/weavertest`, APOC plugin enabled
- Redis: no auth (empty password)

Production credentials are injected via environment variables / secrets — see
`../.env.example` for the variable names. Never hardcode production secrets in
compose files.

## Volumes

| Stack | Volumes |
|-------|---------|
| test | `weaver_pg_data`, `weaver_neo4j_data`, `weaver_neo4j_logs`, `weaver_redis_data` |
| verify | `weaver_pg2_data`, `weaver_neo4j2_data`, `weaver_neo4j2_logs` (Redis reuses test stack) |
| prod | Defined inline in `docker-compose.yml` |

## Health Checks

All stacks define health checks. After `up -d`, poll until all services report
`healthy`:

```bash
docker compose -f docker/docker-compose.test.yml ps --format 'table {{.Service}}\t{{.Status}}'
```

Expected: `pgvector` / `neo4j` / `redis` all show `(healthy)`.

## Cross-Instance Verification Flow

1. Start test stack (`docker-compose.test.yml`) — primary instance on ports
   5432/7687.
2. Run the pipeline to populate data (see `../scripts/pipeline.py`).
3. Export data via `../scripts/data_io.py` to DuckDB / LadybugDB files.
4. Start verify stack (`docker-compose.verify.yml`) — second instance on ports
   5433/7688.
5. Import DuckDB → PG2 (port 5433) via `data_io.py import --from duckdb --to postgres`.
6. Compare row counts and content hashes between the two PG instances and
   between Neo4j and LadybugDB. The project's `tests/integration/` suite
   covers the canonical verification path.

## Hybrid Test Stacks (Phase 3 / Phase 4)

For testing cross-database combinations beyond the primary (PG+Neo4j) and
full-fallback (DuckDB+LadybugDB) stacks, Weaver ships a profile-based
hybrid test compose file:

| Profile | Backends | Purpose | API Port |
|---------|----------|---------|----------|
| `phase3` | PostgreSQL + LadybugDB | Relational primary, graph fallback — validates Article slim-down (design.md §D2): PG holds title/score, LadybugDB holds `pg_id` only | 18014 |
| `phase4` | DuckDB + Neo4j | Graph primary, relational fallback — validates that graph-first deployments still serve search correctly when the relational store is file-backed | 18015 |

### Starting Hybrid Stacks

```bash
# Phase 3: PG + LadybugDB (force Neo4j fallback by leaving NEO4J__PASSWORD empty)
docker compose -f docker/docker-compose.hybrid-test.yml --profile phase3 up -d

# Phase 4: DuckDB + Neo4j (force PG fallback by leaving POSTGRES__DSN empty)
docker compose -f docker/docker-compose.hybrid-test.yml --profile phase4 up -d

# Tear down (keeps volumes)
docker compose -f docker/docker-compose.hybrid-test.yml --profile phase3 down
```

### Running Phase 3/4 Integration Tests

```bash
# Phase 3 tests (auto-skipped if WEAVER_POSTGRES__DSN is unset or NEO4J__PASSWORD is set)
WEAVER_POSTGRES__DSN=postgresql+asyncpg://postgres:weavertest@localhost:5432/weaver \
WEAVER_NEO4J__PASSWORD= \
uv run pytest tests/integration/api/test_hybrid_mode_pg_ladybug.py -m integration -v

# Phase 4 tests (auto-skipped if NEO4J__PASSWORD is unset or POSTGRES__DSN is set)
WEAVER_POSTGRES__DSN= \
WEAVER_NEO4J__URI=bolt://localhost:7687 \
WEAVER_NEO4J__PASSWORD=weavertest \
uv run pytest tests/integration/api/test_hybrid_mode_duckdb_neo4j.py -m integration -v
```

### Aggregating Results

After running Phase 3 and/or Phase 4, aggregate results across all four
phases (Phase 1 + Phase 2 + Phase 3 + Phase 4) and compare core endpoint
response consistency:

```bash
uv run python scripts/aggregate_hybrid_results.py
```

Output: `specmark/changes/web-search-and-db-optimization/records/hybrid_comparison.json`

## See Also

- `../CLAUDE.md` — "数据库故障转移" section for the fallback contract
- `../.env.example` — Phase 1 (PG+Neo4j+Redis), Phase 2 (DuckDB+LadybugDB),
  Phase 3 (PG+LadybugDB), and Phase 4 (DuckDB+Neo4j) environment variable
  examples
- `../scripts/README.md` — `data_io.py` subcommand reference
