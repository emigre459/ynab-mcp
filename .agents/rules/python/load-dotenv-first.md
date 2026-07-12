---
description: API keys live in .env at the project root. Load it before any external API call; on failure, inspect .env for missing/misnamed keys.
appliesTo: "**/*.py"
---

# Load `.env` first

API keys for this project live in `.env` at the project root. Any code, script,
or notebook cell that calls an external API must load `.env` first:

```python
from dotenv import load_dotenv
load_dotenv()            # or load_dotenv(PROJECT_ROOT / ".env") as in-repo scripts do
```

Put the load at the very top of any runnable artifact.

**Why:** Credentials are never hardcoded and never assumed to be in the shell env.
A disabled client (e.g. an LLM observability tracer or third-party API client
silently dropping all calls when its `*_API_KEY` / `*_PUBLIC_KEY` is unset) is
a common, hard-to-spot failure.

**On failure:** if an API call still fails after loading `.env`, inspect `.env`
and diff against `.env.example` (the canonical key names) to find a missing or
misnamed key, and surface concrete remediation (which key, expected name) —
don't fail silently or guess. See `fail-hard-not-warn.md`. Use `uv run python`
so the pinned venv + env resolve (`uv-python.md`).
