.PHONY: help install dev-install start stop restart test test-unit test-integration test-cov test-scripts lint format type-check lint-imports check openapi clean \
        docker-build docker-build-dev docker-clean docker-clean-dev release mirror

IMAGE_NAME ?= simulation-harness
IMAGE_TAG  ?= latest

# Default target
help:
	@echo "Simulation Harness - Available targets:"
	@echo ""
	@echo "  Setup:"
	@echo "    install          Install production dependencies"
	@echo "    dev-install      Install development dependencies"
	@echo ""
	@echo "  Running:"
	@echo "    start            Start the harness server"
	@echo "    stop             Stop the harness server"
	@echo "    restart          Restart the harness server"
	@echo ""
	@echo "  Testing:"
	@echo "    test             Run all tests"
	@echo "    test-unit        Run unit tests only"
	@echo "    test-integration Run integration tests only"
	@echo "    test-cov         Run tests with coverage report"
	@echo "    test-scripts     Run the shell script test suite"
	@echo ""
	@echo "  Code Quality:"
	@echo "    lint             Run ruff linter"
	@echo "    format           Format code with ruff"
	@echo "    type-check       Run mypy type checker"
	@echo "    lint-imports     Check architectural import boundaries"
	@echo "    check            Run lint, type-check, import + format check (CI mode)"
	@echo "    openapi          Regenerate openapi.json from the FastAPI app"
	@echo ""
	@echo "  Releasing:"
	@echo "    release          Cut a release (VERSION=X.Y.Z, required)"
	@echo "    mirror           Publish a release to the external mirror (VERSION optional)"
	@echo ""
	@echo "  Cleanup:"
	@echo "    clean            Remove generated files and caches"
	@echo ""
	@echo "  Docker:"
	@echo "    docker-build     Build production image (IMAGE_NAME:IMAGE_TAG)"
	@echo "    docker-build-dev Build dev image via docker compose (IMAGE_NAME:dev)"
	@echo "    docker-clean     Remove production image"
	@echo "    docker-clean-dev Remove dev image and compose artefacts"

# Installation targets
install:
	uv sync --no-dev

dev-install:
	uv sync --extra dev

# Running targets
start:
	@echo "Starting Simulation Harness..."
	@if [ -f .harness.pid ]; then \
		echo "Harness appears to be already running (PID file exists)"; \
		echo "Run 'make stop' first or remove .harness.pid if stale"; \
		exit 1; \
	fi
	@uv run python -m simulation_harness & echo $$! > .harness.pid
	@echo "Harness started with PID $$(cat .harness.pid)"
	@echo "Logs: tail -f simulation_harness.log (if configured)"

stop:
	@if [ -f .harness.pid ]; then \
		echo "Stopping Simulation Harness (PID $$(cat .harness.pid))..."; \
		kill $$(cat .harness.pid) 2>/dev/null || echo "Process not found (may have already stopped)"; \
		rm -f .harness.pid; \
		echo "Harness stopped"; \
	else \
		echo "No PID file found. Harness may not be running."; \
	fi

restart: stop
	@sleep 2
	@$(MAKE) start

# Testing targets
test:
	uv run pytest

test-unit:
	uv run pytest tests/unit/

test-integration:
	uv run pytest tests/integration/

test-cov:
	uv run pytest --cov=simulation_harness --cov-report=html --cov-report=term
	@echo ""
	@echo "Coverage report generated in htmlcov/index.html"

test-scripts:
	@for t in scripts/tests/test-*.sh; do echo "== $$t"; bash "$$t" || exit 1; done

# Code quality targets
lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

type-check:
	uv run mypy

lint-imports:
	uv run lint-imports

check: lint type-check lint-imports
	uv run ruff format --check src/ tests/
	@echo ""
	@echo "✓ All checks passed"

# Regenerate the static OpenAPI spec from the FastAPI app
openapi:
	uv run python -m simulation_harness.openapi_export > openapi.json
	@echo "Wrote openapi.json"

# Release and mirroring targets
release:
ifndef VERSION
	$(error VERSION is required, e.g. make release VERSION=0.1.0)
endif
	./scripts/release.sh $(VERSION)

mirror:
	./scripts/mirror-release.sh $(VERSION)

# Cleanup target
clean:
	@echo "Cleaning up generated files..."
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage
	rm -rf .ruff_cache
	rm -rf dist
	rm -rf build
	rm -rf *.egg-info
	rm -f .harness.pid
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "Cleanup complete"

# Docker targets
docker-build:
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

docker-build-dev:
	docker compose build

docker-clean:
	docker rmi $(IMAGE_NAME):$(IMAGE_TAG) 2>/dev/null || echo "Image $(IMAGE_NAME):$(IMAGE_TAG) not found"

docker-clean-dev:
	docker compose down --rmi local 2>/dev/null || true
	docker rmi $(IMAGE_NAME):dev 2>/dev/null || echo "Image $(IMAGE_NAME):dev not found"

# Made with Bob
