REPO_ROOT := $(shell git rev-parse --show-toplevel)
include mk/shared.mk

# Pass the `make init` inputs to recipe shells as environment variables, read in
# the recipe as $$STACK / $$PROJECT_NAME / $$DESCRIPTION (shell expansion) rather
# than $(VAR) (make interpolation into the command text). This keeps shell-special
# characters — quotes, backticks, spaces, &, ; — safe in a name/description.
# Caveat: a *literal* `$` is still interpreted by make for any command-line
# variable ($HOME -> OME), so escape it as `$$` (e.g. DESCRIPTION='costs $$5').
# Undefined for other targets — harmless.
export STACK
export PROJECT_NAME
export DESCRIPTION

# --- Template machinery (the init/apply scripts + tests/template that build new
# repos; present only pre-init, removed by `make init`). These targets exist so
# CI and hooks orchestrate machinery checks through make — never raw commands. ---

.PHONY: tooling_deps
tooling_deps: ## Install the template-tooling env (machinery only)
	@uv sync --dev

.PHONY: machinery_format
machinery_format: ## Auto-format the template machinery (black)
	@uv run black scripts/ tests/

.PHONY: machinery_lint
machinery_lint: ## Lint the template machinery (black --check + ruff + mypy)
	@uv run black --check scripts/ tests/
	@uv run ruff check scripts/ tests/
	@uv run mypy

.PHONY: machinery_tests
machinery_tests: ## Test the template machinery
	@uv run pytest tests/template -v --tb=short

.PHONY: deps
deps: tooling_deps ## Install tooling + both stacks' dependencies
	@$(MAKE) -C stacks/python deps
	@$(MAKE) -C stacks/react deps

.PHONY: format
format: machinery_format ## Format machinery + both stacks
	@$(MAKE) -C stacks/python format
	@$(MAKE) -C stacks/react format

.PHONY: lint
lint: machinery_lint ## Lint machinery + both stacks
	@$(MAKE) -C stacks/python lint
	@$(MAKE) -C stacks/react lint

.PHONY: tests
tests: machinery_tests ## Machinery tests + both stacks' tests
	@$(MAKE) -C stacks/python tests
	@$(MAKE) -C stacks/react tests

.PHONY: coverage
coverage: ## Coverage (80% gate) for both stacks
	@$(MAKE) -C stacks/python coverage
	@$(MAKE) -C stacks/react coverage

.PHONY: security
security: ## Security scan for both stacks
	@$(MAKE) -C stacks/python security
	@$(MAKE) -C stacks/react security

.PHONY: pr_check
pr_check: lint tests ## lint + tests across machinery and both stacks

.PHONY: init
# The init inputs are read from the environment as $$VAR (shell), NOT interpolated
# as $(VAR) into the command text. `export` (top of file) passes the command-line
# variables' literal values through to the recipe's environment, and the shell
# expands them inside double quotes without re-parsing — so a PROJECT_NAME or
# DESCRIPTION containing ", $, or ` can't truncate args, trigger expansion, or be
# mangled by make's own $-handling.
init: ## Initialize this template into a single-stack project. Usage: make init STACK=python|react PROJECT_NAME="name" DESCRIPTION="desc"
	@# Run with bare python3 (the script is stdlib-only) — NOT `uv run` — so a
	@# frontend-only dev who picks the React stack never has to install uv just to
	@# initialize. python3 is standard on macOS/Linux; uv is only needed if you
	@# choose the Python stack.
	@python3 scripts/init_template.py --stack "$$STACK" --project-name "$$PROJECT_NAME" --description "$$DESCRIPTION"
