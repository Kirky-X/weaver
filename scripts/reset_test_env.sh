#!/usr/bin/env bash
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Reset and start Docker test environment for full pipeline testing.

Usage:
    ./reset_test_env.sh [--clean] [--wait]

Options:
    --clean   Stop containers and remove volumes before starting
    --wait    Wait for all services to be healthy before exiting
"""

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker/docker-compose.dev.yml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Parse arguments
CLEAN=false
WAIT=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --clean)
            CLEAN=true
            shift
            ;;
        --wait)
            WAIT=true
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Usage: $0 [--clean] [--wait]"
            exit 1
            ;;
    esac
done

# Get compose services (exclude 'app' service)
COMPOSE_SERVICES="postgres redis neo4j"

log_info "Docker Compose file: $COMPOSE_FILE"
log_info "Services to manage: $COMPOSE_SERVICES"

# Step 1: Stop and optionally clean
if [[ "$CLEAN" == true ]]; then
    log_info "Stopping containers and removing volumes..."
    docker compose -f "$COMPOSE_FILE" down -v --remove-orphans 2>/dev/null || true
    log_info "Volumes removed."
else
    log_info "Stopping containers (keeping volumes)..."
    docker compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true
fi

# Step 2: Start services
log_info "Starting Docker services..."
docker compose -f "$COMPOSE_FILE" up -d $COMPOSE_SERVICES

# Step 3: Wait for health (if --wait)
if [[ "$WAIT" == true ]]; then
    log_info "Waiting for services to be healthy..."

    # Wait for PostgreSQL
    log_info "  Waiting for PostgreSQL (port 5432)..."
    for i in {1..30}; do
        if docker exec weaver_postgres pg_isready -U postgres >/dev/null 2>&1; then
            log_info "  ✓ PostgreSQL ready"
            break
        fi
        if [[ $i -eq 30 ]]; then
            log_error "PostgreSQL failed to start after 30 attempts"
            exit 1
        fi
        sleep 2
    done

    # Wait for Redis
    log_info "  Waiting for Redis (port 6379)..."
    for i in {1..15}; do
        if docker exec weaver_redis redis-cli ping >/dev/null 2>&1; then
            log_info "  ✓ Redis ready"
            break
        fi
        if [[ $i -eq 15 ]]; then
            log_error "Redis failed to start after 15 attempts"
            exit 1
        fi
        sleep 2
    done

    # Wait for Neo4j
    log_info "  Waiting for Neo4j (port 7474)..."
    for i in {1..30}; do
        if docker exec weaver_neo4j wget --no-verbose --tries=1 --spider localhost:7474 >/dev/null 2>&1; then
            log_info "  ✓ Neo4j ready"
            break
        fi
        if [[ $i -eq 30 ]]; then
            log_warn "Neo4j health check timeout (may still be starting APOC plugin)"
        fi
        sleep 3
    done

    log_info "All services started successfully!"
else
    log_info "Services started (use --wait to poll for health)"
fi

# Print status
echo ""
docker compose -f "$COMPOSE_FILE" ps $COMPOSE_SERVICES
echo ""
log_info "Environment ready. Run the test with:"
echo "    uv run python scripts/run_36kr_full_pipeline.py"
