# ─────────────────────────────────────────────────────────────
#  Chat Server — Developer task runner
#  Usage: make <target>
#  Run `make help` to list all available targets.
# ─────────────────────────────────────────────────────────────

# Treat every target as a command, not a file name
.PHONY: help \
        install install-dev \
        run run-worker run-beat \
        db-init db-migrate db-upgrade db-downgrade db-history db-reset \
        test test-unit test-integration test-ws test-cov \
        lint format typecheck \
        clean clean-pyc clean-cache clean-logs

# ── Python / venv paths ──────────────────────────────────────
PYTHON      := python3
VENV        := .venv
VENV_BIN    := $(VENV)/bin
PIP         := $(VENV_BIN)/pip
PYTEST      := $(VENV_BIN)/pytest
UVICORN     := $(VENV_BIN)/uvicorn
CELERY      := $(VENV_BIN)/celery
ALEMBIC     := $(VENV_BIN)/alembic
BLACK       := $(VENV_BIN)/black
ISORT       := $(VENV_BIN)/isort
FLAKE8      := $(VENV_BIN)/flake8
MYPY        := $(VENV_BIN)/mypy
PRECOMMIT   := $(VENV_BIN)/pre-commit

# ── App settings ─────────────────────────────────────────────
APP_MODULE  := app.main:app
HOST        := 0.0.0.0
PORT        := 8000
LOG_LEVEL   := debug
WORKERS     := 1                   # uvicorn workers (use 1 in dev)
RELOAD      := --reload            # drop this flag in prod


# ══════════════════════════════════════════════════════════════
#  HELP — auto-generated from ## comments
# ══════════════════════════════════════════════════════════════

help:                              ## Show this help message
	@echo ""
	@echo "  Chat Server — available make targets"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""


# ══════════════════════════════════════════════════════════════
#  ENV — virtual environment & dependencies
# ══════════════════════════════════════════════════════════════

install:                           ## Create venv and install base requirements
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements/base.txt

install-dev:                       ## Create venv and install dev requirements (includes base)
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements/dev.txt
	$(PRECOMMIT) install
	$(PRECOMMIT) install-hooks
	@echo ""
	@echo "  Dev environment ready. Activate with: source $(VENV)/bin/activate"
	@echo ""

install-prod:                      ## Install prod requirements only
	$(PIP) install -r requirements/prod.txt


# ══════════════════════════════════════════════════════════════
#  RUN — start application processes
# ══════════════════════════════════════════════════════════════

run:                               ## Start FastAPI dev server (hot reload)
	$(UVICORN) $(APP_MODULE) \
	  --host $(HOST) \
	  --port $(PORT) \
	  --log-level $(LOG_LEVEL) \
	  --workers $(WORKERS) \
	  $(RELOAD)

run-worker:                        ## Start Celery worker (all queues)
	$(CELERY) -A workers.celery_app worker \
	  --loglevel=info \
	  --queues=email_queue,push_queue,moderation_queue,media_queue \
	  --concurrency=4 \
	  --hostname=worker@%h

run-beat:                          ## Start Celery beat scheduler
	$(CELERY) -A workers.celery_app beat \
	  --loglevel=info \
	  --scheduler celery.beat.PersistentScheduler

run-flower:                        ## Start Flower task monitor (Celery UI) on port 5555
	$(CELERY) -A workers.celery_app flower \
	  --port=5555


# ══════════════════════════════════════════════════════════════
#  DB — Alembic migrations
# ══════════════════════════════════════════════════════════════

db-init:                           ## Initialise Alembic (run once — creates alembic.ini)
	$(ALEMBIC) init alembic

db-migrate:                        ## Generate a new migration from model changes
	@read -p "Migration message: " msg; \
	$(ALEMBIC) revision --autogenerate -m "$$msg"

db-upgrade:                        ## Apply all pending migrations (upgrade to head)
	$(ALEMBIC) upgrade head

db-downgrade:                      ## Roll back the most recent migration
	$(ALEMBIC) downgrade -1

db-history:                        ## Show full migration history
	$(ALEMBIC) history --verbose

db-current:                        ## Show current applied migration revision
	$(ALEMBIC) current

db-reset:                          ## ⚠ Drop all tables and re-run all migrations (dev only)
	@echo "WARNING: this will destroy all data in the dev database."
	@read -p "Type 'yes' to continue: " confirm; \
	if [ "$$confirm" = "yes" ]; then \
	  $(ALEMBIC) downgrade base && $(ALEMBIC) upgrade head; \
	else \
	  echo "Aborted."; \
	fi


# ══════════════════════════════════════════════════════════════
#  TEST — pytest suite
# ══════════════════════════════════════════════════════════════

test:                              ## Run the full test suite
	$(PYTEST) tests/ -v

test-unit:                         ## Run unit tests only
	$(PYTEST) tests/unit/ -v

test-integration:                  ## Run integration tests only
	$(PYTEST) tests/integration/ -v

test-ws:                           ## Run WebSocket tests only
	$(PYTEST) tests/ws/ -v

test-cov:                          ## Run full suite with HTML coverage report
	$(PYTEST) tests/ \
	  --cov=app --cov=core --cov=services \
	  --cov-report=term-missing \
	  --cov-report=html:htmlcov
	@echo ""
	@echo "  Coverage report: open htmlcov/index.html"
	@echo ""

test-file:                         ## Run a single test file: make test-file F=tests/unit/test_jwt.py
	$(PYTEST) $(F) -v


# ══════════════════════════════════════════════════════════════
#  LINT — code quality
# ══════════════════════════════════════════════════════════════

lint:                              ## Run flake8 linter across all source packages
	$(FLAKE8) app/ core/ db/ cache/ services/ workers/ schemas/

format:                            ## Auto-format with black + isort
	$(BLACK) app/ core/ db/ cache/ services/ workers/ schemas/ tests/
	$(ISORT) app/ core/ db/ cache/ services/ workers/ schemas/ tests/

format-check:                      ## Check formatting without modifying files (CI-safe)
	$(BLACK) --check app/ core/ db/ cache/ services/ workers/ schemas/ tests/
	$(ISORT) --check-only app/ core/ db/ cache/ services/ workers/ schemas/ tests/

typecheck:                         ## Run mypy static type checker
	$(MYPY) app/ core/ db/ cache/ services/ workers/ schemas/

precommit-run:                     ## Run all pre-commit hooks against every file
	$(PRECOMMIT) run --all-files

precommit-update:                  ## Update all pre-commit hook versions
	$(PRECOMMIT) autoupdate


# ══════════════════════════════════════════════════════════════
#  CLEAN — remove generated artefacts
# ══════════════════════════════════════════════════════════════

clean-pyc:                         ## Remove all __pycache__ and .pyc files
	find . -type d -name "__pycache__" \
	  -not -path "./.venv/*" \
	  -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" \
	  -not -path "./.venv/*" \
	  -delete 2>/dev/null || true

clean-cache:                       ## Remove pytest, mypy, and coverage caches
	rm -rf .pytest_cache .mypy_cache .coverage htmlcov coverage.xml

clean-logs:                        ## Remove local log files
	find logs/ -type f -name "*.log" -delete 2>/dev/null || true

clean:                             ## Run all clean targets
	$(MAKE) clean-pyc
	$(MAKE) clean-cache
	$(MAKE) clean-logs
	@echo "Clean complete."