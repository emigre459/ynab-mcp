---
description: Code style, type safety, component structure, and testing conventions for the React + TypeScript stack
appliesTo: "**/*.{ts,tsx}"
---

# React + TypeScript best practices

## Tooling (run via the Makefile)

- **Format + lint:** Biome (`make lint` / `make format`). Biome is configured to match
  Gridium's existing Prettier output: single quotes, semicolons, trailing commas
  everywhere, 2-space indent, 80-col width, always-parenthesized arrow params.
- **Types:** `tsc --noEmit` (strict mode) is part of `make lint`. No `any` without a
  written justification; prefer `unknown` + narrowing.
- **Tests:** Vitest + Testing Library (`make tests`). Test user-visible behavior via
  the DOM, not implementation details. Coverage gate is 80% (`make coverage`).

## Components

- Function components only; no class components.
- One component per file. Component files are **PascalCase** (`Button.tsx`); their
  colocated tests are `Button.test.tsx`.
- Hooks rules: call hooks unconditionally at the top level; custom hooks are
  `useFoo`-named and live next to their consumer or in `src/hooks/`.
- Keep components small and focused; lift shared logic into hooks or `src/lib/`.

## Imports & structure

- Use ES module imports. Prefer named exports; default-export only the component a
  file is named for.
- Co-locate component, styles, and test. Split by feature, not by technical layer.

## Error handling

- Fail loud in development: throw on programmer errors; do not silently swallow.
- User-facing async failures surface through error boundaries / explicit UI states,
  never an empty catch.
