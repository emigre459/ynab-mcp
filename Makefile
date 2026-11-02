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

.PHONY: e2e
e2e: ## Run E2E tests (spawns the real stdio server via `uv run ynab-mcp`)
	@uv run pytest -m e2e -v --tb=short

.PHONY: integration
integration: ## Run integration tests (real SDK/HTTP stack against a local mock server, no live YNAB)
	@uv run pytest -m integration -v --tb=short --no-cov

.PHONY: run
run: ## Run the YNAB MCP stdio server (reads .env for your real YNAB_PAT)
	@uv run ynab-mcp

# Inspector v2 defaults ad-hoc stdio targets to the legacy (<= 2025-11-25)
# handshake era; force the modern 2026-07-28 era. Override with
# `make inspect INSPECTOR_ERA=legacy` (or `auto`) to exercise the old era.
INSPECTOR := npx -y @modelcontextprotocol/inspector@latest
INSPECTOR_ERA ?= modern

.PHONY: inspect
inspect: ## Launch MCP Inspector v2 web UI against the stdio server (2026-07-28 era)
	@$(INSPECTOR) --protocol-era $(INSPECTOR_ERA) uv run ynab-mcp

.PHONY: inspect-cli
inspect-cli: ## Browser-free smoke check: list tools via Inspector v2 CLI (2026-07-28 era)
	@$(INSPECTOR) --cli --protocol-era $(INSPECTOR_ERA) uv run ynab-mcp --method tools/list

.PHONY: coverage
coverage: ## pytest with coverage + 80% gate
	@uv run pytest --cov=src --cov-report=term-missing --cov-report=xml --cov-fail-under=80

.PHONY: security
security: ## bandit SAST scan
	@uv run bandit -r src/

.PHONY: pr_check
pr_check: lint tests ## lint + tests for PR readiness
