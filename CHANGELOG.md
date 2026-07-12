# Changelog

## 2026-07-03
- Make `.agents/skills/` harness-agnostic: add the `harness-agnostic-skills` shared rule (canonical paths, skill-root-relative bundled files, frontmatter portability), normalize `review-skill` + `build-from-issue` path references, and wire `AGENTS.md` (#4)
- Add design spec + implementation plan for harness-agnostic skills (#4)
- Guard Step 1f body-fallback jq against a null issue body (#26)
- build-from-issue: add branch-mismatch gate (Step 1b) and parent-epic context + staleness gate (Step 1f) (#25)
- build-from-issue: push+GH-link for spec/plan reviews; add skill-sync rule (#23)

## 2026-06-27
- Add open-PR / vulnerability guard (Step 2b) to build-from-issue (#22)
- ci: bump actions/checkout from 6 to 7 (#9)

## 2026-06-26
- Relax requires-python to >=3.13.5,<3.14 + CI reads .python-version (#17)
- Fix Dependabot ecosystems to match real package managers (#10)
- deps: bump vite from 6.4.3 to 8.0.16 in /stacks/react (#6)
- deps: bump jsdom from 25.0.1 to 29.1.1 in /stacks/react (#7)

## 2026-06-10
- fix: rewrite ci.yml working-directory to root + substitute lockfile name on init; add root coverage/security targets
- fix: generalize the example in fetch-library-docs-first (drop langfuse-specific reference)

## 2026-06-09
- fix: scope react biome.json to the app's own files so post-init lint ignores agent-infra/.venv
- docs: README with required harness-agnostic interview prompt
- feat: init_template initialize() promote/prune/rewrite/self-destruct (TDD)
- feat: init_template marker/placeholder text-transform helpers (TDD)
- fix: apply merge settings via typed JSON body (gh -f sends strings, repo PATCH needs JSON booleans)
- feat: apply_repo_settings.py with diff/PUT/POST/no-op logic (TDD)
- feat: canonical .github/repo-settings (main ruleset + PR-merge prefs)
- feat: dual-stack CI (python/react/template jobs) + dependabot + PR template
- feat: root dispatcher Makefile (delegates to both stacks + owns init target)
- refactor: tighten react exemplar — testable App, istanbul comment fix, userEvent.setup()
- feat: runnable React.ts/bun stack scaffold (Biome snapmeter formatting, Vitest) with green gates
- feat: runnable Python/uv stack scaffold with green quality gates
- feat: mk/shared.mk — shared make targets (help, cc, apply_repo_settings)
- feat: stack-aware Stop hook + permission hook + trimmed settings.json
- feat: AGENTS.md dual-stack router + CLAUDE.md import + cursor/mcp config
- refactor: canonical .agents/skills + single .claude/skills symlink (drop conf-driven sync)
- chore: disable stale Stop hook during build (Task 7 reinstalls stack-aware version)
- feat: react agent rules in .agents/rules/react (new Gridium frontend conventions)
- fix: generalize langfuse example + unify package placeholder in python rules
- feat: python agent rules in .agents/rules/python (ported + genericized)
- feat: shared agent rules in .agents/rules/shared (ported from gridium-agent)
- chore: root tooling env + gitignore; drop broken Makefile and skill-sync script
- docs: implementation plan for dual-stack CI/CD + testing template (issue #1)
- docs: design for dual-stack CI/CD + testing template (issue #1)
- Early commit of stuff that will be useful to power the rest of the template build-out via claude code
- Initial commit
