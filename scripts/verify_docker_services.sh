#!/usr/bin/env bash
# Verify Docker services connectivity for Weaver test stack.
#
# Usage:
#   scripts/verify_docker_services.sh [stack]
#     stack = test (default) | verify
#
# - test:   PG=5432  Neo4j Bolt=7687  Redis=6379
# - verify: PG=5433  Neo4j Bolt=7688  (Redis 复用 test 栈)
#
# Exits 0 if all reachable, 1 otherwise. Output JSON-like for parseability.

set -euo pipefail

STACK="${1:-test}"

if [[ "$STACK" == "test" ]]; then
  PG_PORT=5432
  NEO4J_BOLT_PORT=7687
  NEO4J_HTTP_PORT=7474
  REDIS_PORT=6379
elif [[ "$STACK" == "verify" ]]; then
  PG_PORT=5433
  NEO4J_BOLT_PORT=7688
  NEO4J_HTTP_PORT=7475
  REDIS_PORT=6379  # 复用 test 栈
else
  echo "ERROR: unknown stack '$STACK' (expected: test|verify)" >&2
  exit 2
fi

PG_USER="${PG_USER:-postgres}"
PG_PASSWORD="${PG_PASSWORD:-weavertest}"
PG_DB="${PG_DB:-weaver}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-weavertest}"

PASS=0
FAIL=0

check_pg() {
  local port="$1"
  echo "--- postgres (port ${port}) ---"
  if command -v psql >/dev/null 2>&1; then
    if PGPASSWORD="$PG_PASSWORD" psql -h localhost -p "$port" -U "$PG_USER" -d "$PG_DB" \
        -c 'SELECT version();' -t -A 2>/dev/null | head -1; then
      echo "postgres: OK"
      PASS=$((PASS+1))
    else
      echo "postgres: FAIL"
      FAIL=$((FAIL+1))
    fi
  else
    echo "psql not installed; skipping (consider: apt-get install postgresql-client)"
    FAIL=$((FAIL+1))
  fi
}

check_neo4j() {
  local bolt_port="$1"
  echo "--- neo4j (bolt port ${bolt_port}) ---"
  if command -v cypher-shell >/dev/null 2>&1; then
    if cypher-shell -a "bolt://localhost:${bolt_port}" -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
        'RETURN 1 AS n;' 2>/dev/null | grep -q '^1$'; then
      echo "neo4j: OK"
      PASS=$((PASS+1))
    else
      echo "neo4j: FAIL"
      FAIL=$((FAIL+1))
    fi
  else
    # Fallback: use HTTP endpoint via curl
    if command -v curl >/dev/null 2>&1; then
      local http_port="$NEO4J_HTTP_PORT"
      if curl -sf -o /dev/null "http://localhost:${http_port}/" 2>/dev/null; then
        echo "neo4j (http ${http_port}): OK (cypher-shell not installed, used HTTP probe)"
        PASS=$((PASS+1))
      else
        echo "neo4j (http ${http_port}): FAIL"
        FAIL=$((FAIL+1))
      fi
    else
      echo "neither cypher-shell nor curl available; skipping neo4j"
      FAIL=$((FAIL+1))
    fi
  fi
}

check_redis() {
  local port="$1"
  echo "--- redis (port ${port}) ---"
  if command -v redis-cli >/dev/null 2>&1; then
    if redis-cli -h localhost -p "$port" ping 2>/dev/null | grep -q '^PONG$'; then
      echo "redis: OK"
      PASS=$((PASS+1))
    else
      echo "redis: FAIL"
      FAIL=$((FAIL+1))
    fi
  else
    echo "redis-cli not installed; skipping"
    FAIL=$((FAIL+1))
  fi
}

echo "=== Weaver Docker stack verification: ${STACK} ==="
check_pg "$PG_PORT"
check_neo4j "$NEO4J_BOLT_PORT"
check_redis "$REDIS_PORT"

echo "=== Summary: PASS=${PASS} FAIL=${FAIL} ==="
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
