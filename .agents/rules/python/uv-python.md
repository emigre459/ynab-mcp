---
description: Use uv for all Python execution and dependency management
alwaysApply: true
---

# Python and Dependencies: Use uv

All Python execution and dependency management in this project must use **uv**. Do not use `pip`, `pipenv`, `poetry` (unless explicitly wrapping uv), or bare `python` for running scripts.

## Dependency management

- **Add a package**: `uv add <pkg>` (e.g. `uv add requests`, `uv add pytest --dev`)
- **Remove a package**: `uv remove <pkg>`
- **Sync / install from lockfile**: `uv sync`
- **Update dependencies**: `uv lock --upgrade` or `uv add <pkg> --upgrade`

**Missing module but it’s in pyproject.toml?** Run `uv sync` to install dependencies from the project file (and lockfile). Do not suggest `pip install <pkg>` in that case.

## Running Python

- **Run a script**: `uv run python script.py` or `uv run python -m module.name`
- **Run a CLI tool from the environment**: `uv run <tool>` (e.g. `uv run pytest`, `uv run black`)

## Examples

```bash
# ✅ Add dependency and run script
uv add pandas
uv run python scripts/process.py

# ✅ Run tests
uv run pytest

# ✅ One-off script with inline dependency (if needed)
uv run --with tabulate python report.py
```

Do not suggest or use: `pip install`, `python script.py` (without `uv run`), or other Python/package managers unless the user explicitly requests an exception.
