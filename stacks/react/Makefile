REPO_ROOT := $(shell git rev-parse --show-toplevel)
include $(REPO_ROOT)/mk/shared.mk

.PHONY: deps
deps: ## Install dependencies with bun
	@bun install

.PHONY: format
format: ## Auto-format with Biome
	@bunx biome format --write .

.PHONY: lint
lint: ## Biome check (lint+format) + tsc type-check
	@bunx biome check .
	@bunx tsc --noEmit

.PHONY: tests
tests: ## Run Vitest
	@bunx vitest run

.PHONY: coverage
coverage: ## Vitest with istanbul coverage + 80% gate
	@bunx vitest run --coverage

.PHONY: security
security: ## Dependency CVE audit
	@bun audit

.PHONY: pr_check
pr_check: lint tests ## lint + tests for PR readiness
