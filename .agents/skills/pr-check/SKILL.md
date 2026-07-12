---
name: pr-check
description: Run the full PR readiness check (lint + tests) via `make pr_check`. Use before opening a pull request or when asked to verify code is ready to merge.
compatibility: Requires make (plus the active stack's toolchain — uv for Python, bun for React)
disable-model-invocation: true
allowed-tools: Bash(make pr_check), Bash(make format)
---

Run the full PR readiness check:

```bash
make pr_check
```

`make pr_check` runs `make lint` then `make tests`:
- **lint** is format-check + linting + type-checking (it does NOT modify files):
  Python = `black --check` + `ruff check` + `mypy`; React = `biome check` + `tsc --noEmit`.
- **tests** = the stack's test suite (pytest / vitest).

Report:
1. Lint result — if it reports a formatting violation, run `make format` to auto-fix, then re-run.
2. Test pass/fail summary and total count.
3. Any test failures with file path, line number, and failed assertion.

If checks fail, fix the issues and re-run before finishing.
