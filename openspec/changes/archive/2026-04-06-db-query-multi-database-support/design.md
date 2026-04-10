## Context

The `db_query.py` script provides database inspection capabilities for operators and developers. Currently it supports:
- PostgreSQL: Table record counts via `asyncpg`
- Neo4j: Graph node/relationship counts via `neo4j` driver

The project has implemented a failover system with:
- DuckDB as PostgreSQL backup (SQLAlchemy-based, uses `DuckDBPool`)
- LadybugDB as Neo4j backup (Cypher-compatible, uses `LadybugPool`)

Both backup databases have identical schemas to their primary counterparts. The storage modules already exist in `src/modules/storage/` with repository patterns for each database type.

## Goals / Non-Goals

**Goals:**
- Enable querying DuckDB tables through `db_query.py stats --db duckdb`
- Enable querying LadybugDB graph data through `db_query.py stats --db ladybug`
- Support `article` subcommand for DuckDB queries
- Support `random` subcommand for LadybugDB queries
- Provide unified `--db` parameter for database selection
- Maintain backward compatibility with existing commands

**Non-Goals:**
- No cross-database comparison views (future enhancement)
- No new subcommands beyond existing `stats`, `article`, `random`
- No changes to storage modules or connection pool implementations
- No write operations to any database

## Decisions

### 1. Database Selection via `--db` Parameter

**Decision:** Use repeatable `--db` parameter instead of separate subcommands.

**Rationale:**
- Maintains backward compatibility (default behavior unchanged)
- More flexible than separate commands (`stats-duckdb`, `stats-ladybug`)
- Consistent with existing CLI patterns
- Allows querying multiple databases in single invocation

**Alternatives Considered:**
- Separate subcommands (`stats-duckdb`): Rejected - less flexible, more commands to maintain
- Grouped commands (`stats relational`): Rejected - changes existing behavior, migration burden

### 2. Connection Pool Reuse

**Decision:** Import and use existing `DuckDBPool` and `LadybugPool` from `core.db`.

**Rationale:**
- Avoids code duplication
- Uses tested connection handling
- Consistent with project architecture

### 3. Default Database Selection

**Decision:**
- `stats`: Query all enabled databases by default
- `article`: Default to `postgres`
- `random`: Default to `neo4j`

**Rationale:**
- `stats` is diagnostic - showing all databases is most useful
- `article` and `random` are data retrieval - primary databases are authoritative

### 4. Output Format Consistency

**Decision:** Match existing PostgreSQL/Neo4j output formats exactly.

**Rationale:**
- Familiar interface for operators
- Existing tooling/parsing continues to work
- DuckDB tables mirror PostgreSQL, LadybugDB mirrors Neo4j

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Database connection failures | Print error, continue with other databases; never exit on single DB failure |
| DuckDB/LadybugDB not enabled | Check `settings.{db}.enabled`, skip with informative message |
| Large tables causing slow queries | All stats queries are COUNT operations - bounded performance |
| Connection pool initialization overhead | Pools are created lazily within each command function |

## Migration Plan

No migration required - this is a new feature with full backward compatibility.

**Rollback:** Not applicable - no existing functionality is modified.