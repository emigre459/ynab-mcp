---
description: Use bun for all JS/TS execution and dependency management in this repo — never npm, yarn, or pnpm
alwaysApply: true
---

# JavaScript/TypeScript and Dependencies: Use bun

All JS/TS execution and dependency management in this project must use **bun**. Do
not use `npm`, `yarn`, or `pnpm`.

## Dependency management

- **Add a package**: `bun add <pkg>` (dev: `bun add -d <pkg>`)
- **Remove a package**: `bun remove <pkg>`
- **Install from lockfile**: `bun install`

## Running tools and scripts

- **Run a package.json script**: `bun run <script>` (e.g. `bun run build`)
- **Run a binary from node_modules**: `bunx <tool>` (e.g. `bunx vitest run`, `bunx biome check .`)
- **Run a TS/JS file directly**: `bun <file>`

## Examples

```bash
# ✅ Add dependency and run dev server
bun add zod
bun run dev

# ✅ Lint + test
bunx biome check .
bunx vitest run
```

Do not suggest or use `npm install`, `yarn`, or `pnpm` unless the user explicitly requests an exception.
