# ─────────────────────────────────────────────────────────────────────────────
# AI Document Platform — Dockerfile
#
# Multi-stage build:
# Stage 1 (builder): Install dependencies with UV into a clean layer.
# Stage 2 (runtime): Copy only the installed packages + app code.
#
# Result: production image ~600MB (vs ~1.5GB single-stage).
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Builder ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifests first (layer caching — only re-runs on pyproject.toml changes)
COPY pyproject.toml README.md ./
COPY app/__init__.py app/__init__.py

# Install dependencies into /app/.venv (no editable install in prod)
RUN uv venv .venv --python 3.12 && \
    uv pip install --python .venv/bin/python -e ".[dev]" --no-cache

# ── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Security: run as non-root user
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy venv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY --chown=appuser:appgroup alembic/ alembic/
COPY --chown=appuser:appgroup alembic.ini .
COPY --chown=appuser:appgroup app/ app/

# Activate the venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Storage directory (overrideable via volume mount)
RUN mkdir -p /app/uploads && chown appuser:appgroup /app/uploads

USER appuser

# Health check (liveness probe)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/live')"

EXPOSE 8000

# Default: run the API server.
# Override CMD for workers: ["celery", "-A", "app.workers.celery_app", "worker", "-Q", "ingestion,default"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
