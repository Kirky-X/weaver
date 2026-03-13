FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock ./
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

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

# Run the application
ENV PYTHONPATH=/app/src
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
