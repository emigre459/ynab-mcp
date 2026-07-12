# Shared make targets, included by each stack Makefile via the git repo root so
# they resolve whether the including Makefile is in stacks/<stack>/ or at root.

.PHONY: help
help: ## Print available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

.PHONY: cc
cc: ## Run Claude Code with useful config settings
	@caffeinate -di claude --enable-auto-mode --remote-control

.PHONY: apply_repo_settings
apply_repo_settings: ## Reconcile this repo's main ruleset + PR-merge prefs with .github/repo-settings/ (diff + confirm)
	@python3 $(REPO_ROOT)/scripts/apply_repo_settings.py
