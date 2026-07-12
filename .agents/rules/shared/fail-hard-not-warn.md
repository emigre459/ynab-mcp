---
description: Prefer raising a clear error over warning+fallback. Silent degradation surfaces later as mysterious bugs.
alwaysApply: true
---

# Fail hard, don't warn-and-fall-back

Given a choice between (a) raise and stop vs (b) log a warning / emit a
`FutureWarning` / silently fall back — **always choose (a)**. A clear error with a
remediation hint is friendlier than wrong behavior that ships undetected.

**Why:** Subtle log messages get missed. A `warnings.warn(...)` + fallback
produces correct-looking output today and a mysterious bug weeks later. A loud
failure costs minutes; silent wrong-behavior costs a root-cause hunt.

**Favor these patterns**
- Missing config → `FileNotFoundError("conf/llm_roles.yaml not found. Copy conf/llm_roles.yaml.example or set LLM_ROLES_CONFIG_PATH.")` — ❌ not `warnings.warn(...)` + env fallback.
- Unknown enum → `ValueError(f"Unknown family {val!r}. Expected one of {sorted(KNOWN)}.")` — ❌ not `logger.warning(...) + default`.
- Schema mismatch → let Pydantic raise — ❌ not `try/except ValidationError: return None`.
- Missing test fixture → fail with a clear assert — ❌ not skip silently.
- Removed kwarg → `TypeError(f"{kwarg} was removed in vX; use {new} instead.")` — ❌ not `DeprecationWarning` + remap.

**The one carve-out:** observability code (Langfuse `update_generation`, trace
tagging) is deliberately written to never break the wrapped caller. That
trade-off is scoped to telemetry plumbing only.

Pairs with `load-dotenv-first.md` (surface a missing-key remediation loudly).
