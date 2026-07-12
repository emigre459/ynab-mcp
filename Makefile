REPO_ROOT := $(shell git rev-parse --show-toplevel)
include $(REPO_ROOT)/mk/shared.mk

.PHONY: deps
deps: ## Install runtime + dev dependencies
	@uv sync --dev

.PHONY: format
format: ## Auto-format with black
	@uv run black src/ tests/

.PHONY: lint
lint: ## black --check + ruff + mypy
	@uv run black --check src/ tests/
	@uv run ruff check src/ tests/
	@uv run mypy

.PHONY: tests
tests: ## Run pytest (excludes e2e/integration)
	@uv run pytest -v --tb=short

.PHONY: coverage
coverage: ## pytest with coverage + 80% gate
	@uv run pytest --cov=src --cov-report=term-missing --cov-report=xml --cov-fail-under=80

.PHONY: security
security: ## bandit SAST scan
	@uv run bandit -r src/

.PHONY: pr_check
pr_check: lint tests ## lint + tests for PR readiness
