#!/usr/bin/env bash
# scripts/run_4db_combinations.sh
#
# Start / stop / status / health the Weaver app across 4 DB backend
# combinations used by the dual-failover architecture:
#
#   pg-neo4j       PostgreSQL + Neo4j       (Phase 1 primary)
#   pg-ladybug     PostgreSQL + LadybugDB   (hybrid 1)
#   duckdb-neo4j   DuckDB     + Neo4j       (hybrid 2)
#   duckdb-ladybug DuckDB     + LadybugDB   (Phase 2 fallback)
#
# The active backend is selected by environment variables:
#   - WEAVER_POSTGRES__DSN (non-empty -> PG; empty -> DuckDB fallback)
#   - WEAVER_NEO4J__PASSWORD (non-empty -> Neo4j; empty -> LadybugDB fallback)
#
# Usage:
#   bash scripts/run_4db_combinations.sh <action> [combination]
#
#   action:      start | stop | status | health
#   combination: pg-neo4j | pg-ladybug | duckdb-neo4j | duckdb-ladybug | all
#                (all only valid with status / stop)
#
# This script does NOT modify .env or any file under src/. It only:
#   - sources .env for base config
#   - overrides per-combo env vars in the spawned process's environment
#   - writes PID files to /tmp/weaver_<combo>.pid
#   - writes stdout/stderr to /tmp/weaver_<combo>.log

set -euo pipefail

# ── Constants ────────────────────────────────────────────────────────────────

PG_DSN="postgresql+asyncpg://postgres:weavertest@localhost:5432/weaver"
PG_PASSWORD="weavertest"
NEO4J_PASSWORD="weavertest"
API_KEY="weaver_test_api_key_for_4db_combinations_2026"
ADMIN_API_KEY="weaver_test_admin_api_key_for_4db_combinations_2026"
HOST="127.0.0.1"
# spaCy zh_core_web_lg model is 664MB and takes 3-5 minutes to load on first
# start. Allow up to 7 minutes for /health to come green.
HEALTH_WAIT_SECONDS=420
HEALTH_POLL_INTERVAL=5
STOP_GRACE_SECONDS=10

# Combo -> port
declare -A COMBO_PORTS=(
  ["pg-neo4j"]=18001
  ["pg-ladybug"]=18002
  ["duckdb-neo4j"]=18003
  ["duckdb-ladybug"]=18004
)

# Combo -> WEAVER_POSTGRES__ENABLED value ("true" = use PG, "false" = DuckDB fallback)
# Using the enabled flag (rather than empty DSN) gives deterministic fallback
# behavior: create_strategy() skips the PostgreSQL attempt entirely instead
# of relying on connection failure. See strategy.py::create_strategy.
declare -A COMBO_PG_ENABLED=(
  ["pg-neo4j"]="true"
  ["pg-ladybug"]="true"
  ["duckdb-neo4j"]="false"
  ["duckdb-ladybug"]="false"
)

# Combo -> WEAVER_NEO4J__ENABLED value ("true" = use Neo4j, "false" = LadybugDB fallback)
declare -A COMBO_NEO4J_ENABLED=(
  ["pg-neo4j"]="true"
  ["pg-ladybug"]="false"
  ["duckdb-neo4j"]="true"
  ["duckdb-ladybug"]="false"
)

# Combo -> WEAVER_LADYBUG__DB_PATH value. LadybugDB uses a single-writer
# file lock, so pg-ladybug and duckdb-ladybug CANNOT share the same file.
# We point duckdb-ladybug at a byte-identical copy (data/weaver_ladybug2.lbug)
# so both instances can run concurrently while preserving data parity.
# See specmark/archive/2026-07-20-db-consistency-verify/design.md §"4 DB 组合测试架构".
declare -A COMBO_LADYBUG_PATH=(
  ["pg-neo4j"]=""
  ["pg-ladybug"]="data/weaver.lbug"
  ["duckdb-neo4j"]=""
  ["duckdb-ladybug"]="data/weaver_ladybug2.lbug"
)

# Combo -> WEAVER_DUCKDB__DB_PATH value. DuckDB also uses a single-writer
# file lock, so duckdb-neo4j and duckdb-ladybug CANNOT share the same file.
# We point duckdb-ladybug at a byte-identical copy (data/weaver_duckdb2.duckdb)
# so both DuckDB instances can run concurrently while preserving data parity.
declare -A COMBO_DUCKDB_PATH=(
  ["pg-neo4j"]=""
  ["pg-ladybug"]=""
  ["duckdb-neo4j"]="data/weaver.duckdb"
  ["duckdb-ladybug"]="data/weaver_duckdb2.duckdb"
)

ALL_COMBOS=(pg-neo4j pg-ladybug duckdb-neo4j duckdb-ladybug)

# ── Colors ───────────────────────────────────────────────────────────────────

if [[ -t 1 ]]; then
  GREEN=$'\033[0;32m'
  RED=$'\033[0;31m'
  YELLOW=$'\033[0;33m'
  BLUE=$'\033[0;34m'
  NC=$'\033[0m'
else
  GREEN=""
  RED=""
  YELLOW=""
  BLUE=""
  NC=""
fi

# ── Logging helpers ──────────────────────────────────────────────────────────

log_info()  { printf '%s[INFO]%s %s\n'  "$GREEN"  "$NC" "$*"; }
log_warn()  { printf '%s[WARN]%s %s\n'  "$YELLOW" "$NC" "$*"; }
log_error() { printf '%s[ERROR]%s %s\n' "$RED"    "$NC" "$*" >&2; }
log_step()  { printf '%s[STEP]%s %s\n'  "$BLUE"   "$NC" "$*"; }

# ── Path helpers ─────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

pid_file() { printf '/tmp/weaver_%s.pid\n' "$1"; }
log_file() { printf '/tmp/weaver_%s.log\n' "$1"; }

# ── Validation ───────────────────────────────────────────────────────────────

validate_combo() {
  local combo="$1"
  if [[ -z "${COMBO_PORTS[$combo]:-}" ]]; then
    log_error "Unknown combination: '$combo'"
    log_error "Valid: pg-neo4j | pg-ladybug | duckdb-neo4j | duckdb-ladybug | all"
    exit 2
  fi
}

require_tool() {
  local tool="$1"
  if ! command -v "$tool" >/dev/null 2>&1; then
    log_error "required tool '$tool' not found in PATH"
    exit 1
  fi
}

# ── Env loading & per-combo overrides ────────────────────────────────────────

load_env() {
  local env_path="$PROJECT_ROOT/.env"
  if [[ -f "$env_path" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_path"
    set +a
  else
    log_warn ".env not found at $env_path — using bare environment"
  fi
}

apply_combo_env() {
  local combo="$1"
  # Override .env values for this combination.
  # - WEAVER_POSTGRES__ENABLED=false triggers DuckDB fallback deterministically
  #   (strategy.py::create_strategy skips PG attempt entirely).
  # - WEAVER_NEO4J__ENABLED=false triggers LadybugDB fallback deterministically.
  export WEAVER_POSTGRES__ENABLED="${COMBO_PG_ENABLED[$combo]}"
  export WEAVER_NEO4J__ENABLED="${COMBO_NEO4J_ENABLED[$combo]}"
  # Still set DSN/password so that when enabled=true, PG/Neo4j connect with
  # the correct credentials (overriding any stale .env values). When
  # enabled=false, these are ignored by create_strategy.
  if [[ "${COMBO_PG_ENABLED[$combo]}" == "true" ]]; then
    export WEAVER_POSTGRES__DSN="$PG_DSN"
    export WEAVER_POSTGRES__PASSWORD="$PG_PASSWORD"
  else
    # DuckDB combo: unset both DSN and PASSWORD to prevent cross-combo
    # pollution (Architecture review LOW: previously PASSWORD lingered
    # from a prior pg-* combo in the same shell session).
    unset WEAVER_POSTGRES__DSN
    unset WEAVER_POSTGRES__PASSWORD
  fi
  if [[ "${COMBO_NEO4J_ENABLED[$combo]}" == "true" ]]; then
    export WEAVER_NEO4J__PASSWORD="$NEO4J_PASSWORD"
  else
    unset WEAVER_NEO4J__PASSWORD
  fi
  export WEAVER_API__PORT="${COMBO_PORTS[$combo]}"
  export WEAVER_API__API_KEY="$API_KEY"
  export WEAVER_API__ADMIN_API_KEY="$ADMIN_API_KEY"
  export WEAVER_API__HOST="$HOST"
  # LadybugDB file path override (only set for ladybug combos). Empty string
  # means "use default path" which is fine for the two non-ladybug combos.
  local ladybug_path="${COMBO_LADYBUG_PATH[$combo]:-}"
  if [[ -n "$ladybug_path" ]]; then
    export WEAVER_LADYBUG__DB_PATH="$ladybug_path"
  else
    unset WEAVER_LADYBUG__DB_PATH
  fi
  # DuckDB file path override (only set for duckdb combos). Empty string
  # means "use default path" which is fine for the two pg combos.
  local duckdb_path="${COMBO_DUCKDB_PATH[$combo]:-}"
  if [[ -n "$duckdb_path" ]]; then
    export WEAVER_DUCKDB__DB_PATH="$duckdb_path"
  else
    unset WEAVER_DUCKDB__DB_PATH
  fi
}

# ── Process helpers ──────────────────────────────────────────────────────────

pid_alive() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

read_pid() {
  local combo="$1"
  local pf
  pf="$(pid_file "$combo")"
  if [[ -f "$pf" ]]; then
    cat "$pf" 2>/dev/null || true
  fi
}

fetch_health() {
  local port="$1"
  curl -fsS --max-time 5 "http://${HOST}:${port}/health" 2>/dev/null || true
}

# Parse /health JSON and print per-DB status lines. Tries jq first, falls
# back to python3 / python so the script works without jq installed.
print_health_breakdown() {
  local resp="$1"
  if command -v jq >/dev/null 2>&1; then
    local overall
    overall="$(printf '%s' "$resp" | jq -r '.data.status // "?"' 2>/dev/null || echo "?")"
    printf 'overall: %s\n' "$overall"
    local has_checks
    has_checks="$(printf '%s' "$resp" | jq -r '.data.checks | length' 2>/dev/null || echo "0")"
    if [[ "$has_checks" == "0" ]]; then
      printf '  (no per-DB checks present)\n'
      return 0
    fi
    # Iterate over each check key (postgres / duckdb / neo4j / ladybug / redis / cashews)
    while IFS=$'\t' read -r name status error; do
      local line="  ${name}: ${status}"
      if [[ -n "$error" && "$error" != "null" ]]; then
        line+=" (error: ${error})"
      fi
      printf '%s\n' "$line"
    done < <(printf '%s' "$resp" | jq -r '.data.checks | to_entries[] | [.key, (.value.status // "?"), (.value.error // "")] | @tsv' 2>/dev/null)
    return 0
  fi

  # Fallback: python3 (or python)
  local py_bin="python3"
  if ! command -v python3 >/dev/null 2>&1; then
    py_bin="python"
  fi
  if ! command -v "$py_bin" >/dev/null 2>&1; then
    log_warn "neither jq nor python3 available — skipping per-DB breakdown"
    return 0
  fi
  "$py_bin" - "$resp" <<'PYEOF'
import json, sys
try:
    data = json.loads(sys.argv[1])
except Exception as exc:
    print(f"(failed to parse JSON: {exc})")
    sys.exit(0)
payload = data.get("data", data) if isinstance(data, dict) else {}
overall = payload.get("status", "?")
print(f"overall: {overall}")
checks = payload.get("checks", {})
if not checks:
    print("  (no per-DB checks present)")
else:
    for name, info in checks.items():
        if not isinstance(info, dict):
            print(f"  {name}: {info}")
            continue
        st = info.get("status", "?")
        err = info.get("error")
        line = f"  {name}: {st}"
        if err:
            line += f" (error: {err})"
        print(line)
PYEOF
}

# ── Actions ──────────────────────────────────────────────────────────────────

start_combo() {
  local combo="$1"
  validate_combo "$combo"
  require_tool uv
  require_tool curl
  local port="${COMBO_PORTS[$combo]}"

  # Memory preflight check (Performance review M3): each Weaver instance
  # needs ~3GB (spaCy zh_core_web_lg 664MB + Python runtime + DB pools).
  # Warn if available memory is below the per-instance threshold. The check
  # is advisory (does not abort) because spaCy may share model pages across
  # instances via OS page cache.
  local mem_available_mb
  mem_available_mb="$(awk '/^MemAvailable:/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)"
  if [[ "$mem_available_mb" -gt 0 && "$mem_available_mb" -lt 3072 ]]; then
    log_warn "low memory: ${mem_available_mb}MB available (recommended ≥3072MB per instance)"
  fi

  local existing_pid
  existing_pid="$(read_pid "$combo")"
  if pid_alive "$existing_pid"; then
    log_warn "$combo already running (PID $existing_pid, port $port) — nothing to start"
    exit 0
  fi

  # Clean stale PID file
  if [[ -f "$(pid_file "$combo")" ]]; then
    rm -f "$(pid_file "$combo")"
  fi

  load_env
  apply_combo_env "$combo"

  local lf
  lf="$(log_file "$combo")"

  log_step "Starting $combo on ${HOST}:${port}"
  if [[ "$WEAVER_POSTGRES__ENABLED" == "true" ]]; then
    log_info "  relational: PostgreSQL (enabled=true)"
  else
    log_info "  relational: DuckDB fallback (enabled=false)"
    if [[ -n "${WEAVER_DUCKDB__DB_PATH:-}" ]]; then
      log_info "  duckdb:     $WEAVER_DUCKDB__DB_PATH"
    fi
  fi
  if [[ "$WEAVER_NEO4J__ENABLED" == "true" ]]; then
    log_info "  graph:      Neo4j (enabled=true)"
  else
    log_info "  graph:      LadybugDB fallback (enabled=false)"
    if [[ -n "${WEAVER_LADYBUG__DB_PATH:-}" ]]; then
      log_info "  ladybug:    $WEAVER_LADYBUG__DB_PATH"
    fi
  fi
  log_info "  log: $lf"

  cd "$PROJECT_ROOT"
  # shellcheck disable=SC2086
  nohup uv run python -m src.main > "$lf" 2>&1 < /dev/null &
  local pid=$!
  echo "$pid" > "$(pid_file "$combo")"

  log_info "PID $pid — waiting up to ${HEALTH_WAIT_SECONDS}s for /health …"

  local elapsed=0
  local healthy=0
  while [[ $elapsed -lt $HEALTH_WAIT_SECONDS ]]; do
    if ! pid_alive "$pid"; then
      log_error "$combo process died (PID $pid). Tail of log:"
      tail -n 50 "$lf" >&2 || true
      rm -f "$(pid_file "$combo")"
      exit 1
    fi
    local resp
    resp="$(fetch_health "$port")"
    if [[ -n "$resp" ]]; then
      healthy=1
      break
    fi
    sleep "$HEALTH_POLL_INTERVAL"
    elapsed=$((elapsed + HEALTH_POLL_INTERVAL))
  done

  if [[ $healthy -eq 1 ]]; then
    log_info "$combo started (PID $pid, port $port, health=ok)"
  else
    log_error "$combo did not become healthy within ${HEALTH_WAIT_SECONDS}s"
    log_error "Tail of log:"
    tail -n 50 "$lf" >&2 || true
    # Leave PID file so user can inspect / stop
    exit 1
  fi
}

stop_combo() {
  local combo="$1"
  validate_combo "$combo"
  local pf
  pf="$(pid_file "$combo")"
  if [[ ! -f "$pf" ]]; then
    log_warn "$combo: no PID file at $pf — nothing to stop"
    return 0
  fi
  local pid
  pid="$(cat "$pf" 2>/dev/null || true)"
  if [[ -z "$pid" ]]; then
    log_warn "$combo: PID file empty — removing"
    rm -f "$pf"
    return 0
  fi
  if ! pid_alive "$pid"; then
    log_warn "$combo: process $pid not running — removing stale PID file"
    rm -f "$pf"
    return 0
  fi

  log_step "Stopping $combo (PID $pid)"
  kill "$pid" 2>/dev/null || true

  local waited=0
  while [[ $waited -lt $STOP_GRACE_SECONDS ]]; do
    if ! pid_alive "$pid"; then
      break
    fi
    sleep 1
    waited=$((waited + 1))
  done

  if pid_alive "$pid"; then
    log_warn "$combo: process $pid did not exit after SIGTERM — sending SIGKILL"
    kill -9 "$pid" 2>/dev/null || true
    sleep 1
  fi

  rm -f "$pf"
  if pid_alive "$pid"; then
    log_error "$combo: failed to kill PID $pid"
    return 1
  fi
  log_info "$combo stopped"
}

status_combo() {
  local combo="$1"
  validate_combo "$combo"
  local port="${COMBO_PORTS[$combo]}"
  local pid
  pid="$(read_pid "$combo")"
  local pid_display="-"
  local status="not running"
  if pid_alive "$pid"; then
    pid_display="$pid"
    local resp
    resp="$(fetch_health "$port")"
    if [[ -n "$resp" ]]; then
      status="healthy"
    else
      status="running (no /health)"
    fi
  fi
  printf '%-16s | %-8s | %-6s | %s\n' "$combo" "$pid_display" "$port" "$status"
}

health_combo() {
  local combo="$1"
  validate_combo "$combo"
  local port="${COMBO_PORTS[$combo]}"
  local pid
  pid="$(read_pid "$combo")"
  if ! pid_alive "$pid"; then
    log_error "$combo not running (PID file: $(pid_file "$combo"))"
    exit 1
  fi
  local resp
  resp="$(fetch_health "$port")"
  if [[ -z "$resp" ]]; then
    log_error "$combo: /health did not respond on ${HOST}:${port}"
    exit 1
  fi

  log_info "$combo — raw /health response:"
  printf '%s\n' "$resp"
  log_info "per-DB breakdown:"
  print_health_breakdown "$resp"
}

# ── Usage / dispatch ─────────────────────────────────────────────────────────

usage() {
  cat <<'USAGE'
Usage: bash scripts/run_4db_combinations.sh <action> [combination]

action:
  start    Start Weaver app for the given combination
  stop     Stop Weaver app for the given combination (or all)
  status   Show status for the given combination (or all)
  health   curl /health and parse per-DB status

combination:
  pg-neo4j       PG + Neo4j         (port 18001)
  pg-ladybug     PG + LadybugDB     (port 18002)
  duckdb-neo4j   DuckDB + Neo4j     (port 18003)
  duckdb-ladybug DuckDB + LadybugDB (port 18004)
  all            All combos (only valid with status / stop)
USAGE
}

main() {
  local action="${1:-}"
  local combo="${2:-}"

  if [[ -z "$action" ]]; then
    usage
    exit 1
  fi

  case "$action" in
    start)
      if [[ -z "$combo" || "$combo" == "all" ]]; then
        log_error "start requires a single combination (not 'all')"
        usage
        exit 2
      fi
      start_combo "$combo"
      ;;
    stop)
      if [[ -z "$combo" ]]; then
        usage
        exit 2
      fi
      if [[ "$combo" == "all" ]]; then
        local had_error=0
        for c in "${ALL_COMBOS[@]}"; do
          stop_combo "$c" || had_error=1
        done
        [[ $had_error -eq 0 ]] || exit 1
      else
        stop_combo "$combo"
      fi
      ;;
    status)
      if [[ -z "$combo" ]]; then
        usage
        exit 2
      fi
      printf '%-16s | %-8s | %-6s | %s\n' "combination" "pid" "port" "status"
      if [[ "$combo" == "all" ]]; then
        for c in "${ALL_COMBOS[@]}"; do
          status_combo "$c"
        done
      else
        status_combo "$combo"
      fi
      ;;
    health)
      if [[ -z "$combo" || "$combo" == "all" ]]; then
        log_error "health requires a single combination (not 'all')"
        usage
        exit 2
      fi
      health_combo "$combo"
      ;;
    -h|--help|help)
      usage
      exit 0
      ;;
    *)
      log_error "Unknown action: '$action'"
      usage
      exit 2
      ;;
  esac
}

main "$@"
