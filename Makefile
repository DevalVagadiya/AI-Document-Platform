# ─────────────────────────────────────────────────────────────────────────────
# Makefile — Developer convenience targets
#
# All targets use the .venv Python to stay self-contained.
# Usage: make <target>
# ─────────────────────────────────────────────────────────────────────────────

PYTHON = .venv/Scripts/python
UV     = python -m uv
UVRUN  = $(UV) run

.PHONY: help install install-dev lint format typecheck test test-cov \
        migrate migrate-new server worker docker-up docker-down clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Setup ─────────────────────────────────────────────────────────────────────

install:  ## Create venv and install production deps
	$(UV) venv .venv --python 3.12
	$(UV) pip install --python .venv/Scripts/python -e "."

install-dev:  ## Install all deps including dev
	$(UV) venv .venv --python 3.12
	$(UV) pip install --python .venv/Scripts/python -e ".[dev]"
	$(PYTHON) -m pre_commit install

# ── Code Quality ──────────────────────────────────────────────────────────────

lint:  ## Run Ruff linter
	$(PYTHON) -m ruff check app/ tests/

format:  ## Format code with Ruff
	$(PYTHON) -m ruff format app/ tests/
	$(PYTHON) -m ruff check --fix app/ tests/

typecheck:  ## Run MyPy type checker
	$(PYTHON) -m mypy app/

# ── Testing ───────────────────────────────────────────────────────────────────

test:  ## Run test suite
	$(PYTHON) -m pytest tests/ -v

test-cov:  ## Run tests with coverage report
	$(PYTHON) -m pytest tests/ -v --cov=app --cov-report=term-missing --cov-report=html

test-unit:  ## Run unit tests only
	$(PYTHON) -m pytest tests/unit/ -v

test-integration:  ## Run integration tests only
	$(PYTHON) -m pytest tests/integration/ -v

# ── Database ──────────────────────────────────────────────────────────────────

migrate:  ## Apply all pending Alembic migrations
	$(PYTHON) -m alembic upgrade head

migrate-new:  ## Create a new migration (usage: make migrate-new MSG="description")
	$(PYTHON) -m alembic revision --autogenerate -m "$(MSG)"

migrate-down:  ## Rollback last migration
	$(PYTHON) -m alembic downgrade -1

migrate-history:  ## Show migration history
	$(PYTHON) -m alembic history --verbose

# ── Running ───────────────────────────────────────────────────────────────────

server:  ## Start development server with auto-reload
	$(PYTHON) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:  ## Start Celery worker
	$(PYTHON) -m celery -A app.workers.celery_app worker --loglevel=info -Q ingestion,default

flower:  ## Start Flower monitoring UI
	$(PYTHON) -m celery -A app.workers.celery_app flower --port=5555

# ── Docker ────────────────────────────────────────────────────────────────────

docker-up:  ## Start all services with Docker Compose
	docker compose up -d

docker-down:  ## Stop all services
	docker compose down

docker-logs:  ## Tail logs for all services
	docker compose logs -f

docker-build:  ## Rebuild Docker images
	docker compose build --no-cache

# ── Cleanup ───────────────────────────────────────────────────────────────────

clean:  ## Remove build artifacts, cache, venv
	rm -rf .venv dist build *.egg-info .pytest_cache .mypy_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
