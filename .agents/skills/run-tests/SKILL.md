---
name: run-tests
description: Run the full pytest test suite via `make tests`. Use when verifying tests pass, after making code changes, or when asked to run tests or check if tests pass.
compatibility: Requires uv and make
disable-model-invocation: true
allowed-tools: Bash(make tests)
---

Run the project test suite:

```bash
make tests
```

This executes `uv run pytest -v --tb=short -n auto` (parallelised across all CPU cores).

After the run:
1. Report the pass/fail summary and total count
2. For any failures: show the test name, file path, line number, and the exact assertion that failed
3. If all pass: confirm and note the count

If tests fail and you just wrote the failing code, fix it before considering the task done. Follow the red-green TDD cycle: tests must be green before finishing.
