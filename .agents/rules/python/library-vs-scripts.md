---
description: Pipeline/abstraction logic lives in the library (src/<your_package>/), not in scripts/. Scripts only demo the library API.
appliesTo: "scripts/**/*.py"
---

# Library, not scripts

Pipeline-level abstractions — connectors, registries, dispatchers, protocols,
orchestration helpers — belong in `src/<your_package>/`. Files under `scripts/`
are **demonstrations** of the library API, not where pipeline semantics live.

**Why:** Logic built inside a script gives nothing to a real consumer running
through the library APIs. The library is the product; scripts are showcases.

**How to apply**
- New protocol / ABC / registry / dispatcher / orchestration helper → `src/<your_package>/<module>.py`.
- A script may be updated to *use* a new library API, but keep it thin: build the
  input set, call into the library, print/inspect the result.
- Reframe "make `scripts/foo.py` do X" as "make the library do X, then update the
  script to demonstrate it."
