# Cursor Bugbot — Noise Filters

This file lists categories of findings we explicitly do **not** want from Cursor
Bugbot on PRs in this repo. Bugbot is valuable for catching real bugs — the goal
here isn't to silence it, it's to keep the signal-to-noise ratio high so reviewers
actually read every finding.

If a finding falls into one of the categories below, skip it. If you're unsure
whether a finding qualifies, **default to reporting** — false negatives are worse
than a small amount of noise.

---

## Skip these categories

### 1. Hypothetical edge cases the type system or upstream caller already prevents

Skip "what if this is `None`/`undefined`?" findings when:
- The type signature forbids it (no `| None`, no `Optional[...]`, non-nullable TS type).
- The value is constructed in the same scope immediately before the call.
- A documented caller invariant prevents the case.

**Bad** (skip): "If this list is empty, the loop does nothing." — that's the intended no-op.
**Good** (report): "If this list contains an unexpected element type, the next line throws." — real defect when input shape isn't enforced.

### 2. Style/readability preferences that aren't correctness issues

Skip "extract a helper", "rename this variable", "prefer this idiom", "add a docstring
to this private helper". Formatting and lint are already enforced by the project's
formatter + linter (see `.agents/rules/`); issues those tools would catch don't need
a separate Bugbot finding.

### 3. Test-quality nags that aren't bugs

Skip "this test could be parameterized", "split this into multiple tests", "add a
fixture". The bar for a test finding is that the test is **wrong** (asserts the wrong
thing, false-positive pattern, depends on global/leaked state), not "could be tidier".

### 4. Comment-quality complaints

Skip "this comment is unclear" / "this docstring could be more detailed". A comment
that is **factually wrong** about the code beneath it (lies about behavior, references
a removed symbol) is worth reporting; subjective improvements aren't.

### 5. Demo / example / scaffold complaints

Skip findings that flag clearly-illustrative sample code (starter components, example
modules, demo scripts) for "hardcodes values", "doesn't validate input", or "uses
`print`/`alert` for output". Real application/library code is a different story —
findings there are usually worth reporting.

### 6. Premature error-handling suggestions

Skip "should catch X here" when failure is already handled downstream (an outer
try/except, a per-task executor that isolates failures, or a subsystem documented as
"fail loud, don't swallow" — see `.agents/rules/`).

### 7. Performance micro-optimizations outside hot paths

Skip "memoize this", "this is recompiled each call", "use a set instead of a small
list". Cosmetic perf outside a genuine hot path isn't worth a finding.

### 8. Documentation-shape complaints about AGENTS.md / `.agents/rules/` / config

Skip "this rule is vague" / "this rule contradicts another". Bugbot is for code, not
policy. If you spot a genuine rule inconsistency, raise it in a separate human-facing
comment rather than a code finding.

---

## Always report (don't skip these)

1. **Contract / schema drift** — a producer builds data one way and a consumer reads
   it another (mismatched keys, a schema requiring a field the writer never emits, an
   API shape the caller doesn't satisfy).
2. **Per-item error-isolation gaps** — one element's failure sinks a batch that's
   documented as isolated.
3. **Broken paths / hrefs / imports** — a generated URL, filename, or import path that
   won't resolve.
4. **Type-narrowing regressions** — wrong generic type, wrong key/value pairing in a
   comprehension/map, an unsafe cast (the static type-checker sometimes misses these).
5. **Tests that pass by coincidence** — the assertion targets a value that only appears
   via a fallback path the test isn't actually exercising.
6. **Logic errors** — off-by-one, inverted condition, wrong operator, unhandled state.

When in doubt about a finding's category — report it. We adjust this filter list over
time as patterns emerge.
