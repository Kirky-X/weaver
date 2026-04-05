FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock ./
COPY README.md ./
COPY src ./src

# Install dependencies
RUN uv sync --frozen --no-dev

# Install spaCy models
RUN uv run python -m spacy download zh_core_web_trf \
 && uv run python -m spacy download en_core_web_trf \
 && uv run python -m spacy download xx_ent_wiki_sm

# Install Playwright browsers
RUN uv run playwright install chromium --with-deps

# Expose port
EXPOSE 8000

# Health check (reads dynamic port from .env.weaver)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD PORT=$(grep -E '^WEAVER_ACTUAL_PORT=' /app/.env.weaver 2>/dev/null | cut -d'=' -f2 || echo 8000) && \
  python -c "import requests; requests.get(f'http://localhost:${PORT}/health')" || exit 1

# Run the application
ENV PYTHONPATH=/app/src
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
