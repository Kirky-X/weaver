#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== News Discovery Development Setup ===${NC}"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Docker is not running. Please start Docker first.${NC}"
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}docker-compose is not installed.${NC}"
    exit 1
fi

# Parse command line arguments
COMMAND=${1:-start}

case $COMMAND in
    start)
        echo -e "${GREEN}Starting PostgreSQL, Neo4j, and Redis...${NC}"
        docker-compose -f docker-compose.dev.yml up -d

        echo -e "${GREEN}Waiting for services to be healthy...${NC}"

        # Wait for PostgreSQL
        echo "Waiting for PostgreSQL..."
        until docker exec news_discovery_postgres pg_isready -U postgres > /dev/null 2>&1; do
            sleep 2
        done
        echo -e "${GREEN}PostgreSQL is ready!${NC}"

        # Wait for Neo4j
        echo "Waiting for Neo4j..."
        until curl -s http://localhost:7474 > /dev/null 2>&1; do
            sleep 2
        done
        echo -e "${GREEN}Neo4j is ready!${NC}"

        echo -e "${GREEN}All services started successfully!${NC}"
        echo ""
        echo "Services:"
        echo "  - PostgreSQL: localhost:5432 (user: postgres, pass: postgres, db: news_discovery)"
        echo "  - Neo4j:      localhost:7474 (user: neo4j, pass: neo4j123)"
        echo "  - Redis:       localhost:6379"
        echo ""
        echo "To run the application:"
        echo "  source .venv/bin/activate"
        echo "  uv run alembic upgrade head"
        echo "  uv run uvicorn main:app --reload"
        ;;

    stop)
        echo -e "${YELLOW}Stopping services...${NC}"
        docker-compose -f docker-compose.dev.yml down
        echo -e "${GREEN}Services stopped.${NC}"
        ;;

    restart)
        $0 stop
        $0 start
        ;;

    logs)
        docker-compose -f docker-compose.dev.yml logs -f
        ;;

    status)
        docker-compose -f docker-compose.dev.yml ps
        ;;

    clean)
        echo -e "${YELLOW}Stopping and removing containers and volumes...${NC}"
        docker-compose -f docker-compose.dev.yml down -v
        echo -e "${GREEN}Clean complete.${NC}"
        ;;

    *)
        echo "Usage: $0 {start|stop|restart|logs|status|clean}"
        exit 1
        ;;
esac
