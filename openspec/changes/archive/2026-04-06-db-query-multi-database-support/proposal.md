## Why

The `db_query.py` script currently only supports PostgreSQL and Neo4j queries. The project has implemented DuckDB and LadybugDB as failover backup databases with identical schemas to the primary databases. Operators need the ability to query and verify data in these backup databases independently, especially during failover scenarios or data consistency checks.

## What Changes

- Extend `stats` subcommand to support DuckDB and LadybugDB databases
- Extend `article` subcommand to support DuckDB queries
- Extend `random` subcommand to support LadybugDB queries
- Add `--db` parameter allowing users to specify which database(s) to query
- Support querying multiple databases in a single command execution
- Maintain consistent output format with existing PostgreSQL/Neo4j queries

## Capabilities

### New Capabilities

- `db-query-duckdb`: Query and inspect DuckDB tables (articles, vectors, LLM usage, etc.) through the `db_query.py` script
- `db-query-ladybug`: Query and inspect LadybugDB graph data (nodes, relationships) through the `db_query.py` script

### Modified Capabilities

- `db-query-cli`: Extend existing CLI with `--db` parameter for database selection, enabling multi-database queries in a unified interface

## Impact

- **Modified file**: `scripts/db_query.py` only
- **No API changes**: Internal script modification
- **Dependencies**: Uses existing storage modules (`DuckDBPool`, `LadybugPool`) from `src/core/db/`
- **Backward compatible**: Default behavior queries all enabled databases; existing commands work unchanged