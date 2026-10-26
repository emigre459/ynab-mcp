# FastMCP 4 / MCP Python SDK v2 upgrade — design

Issue: #43 (child 11 of epic #10). Date: 2026-10-26.

## Goal

Move the server from `fastmcp` 3.x (on MCP Python SDK v1) to `fastmcp` 4.x
(on MCP Python SDK v2) so it speaks the MCP `2026-07-28` protocol revision and
picks up the 4.x auth/security hardening — **without adopting any new v4
feature**. Interactive tools / write approval is #45; the MCP Inspector v2 dev
loop is #44.

## Findings that shape the design

A throwaway probe (a scratch copy of `main`@6168154 with only the pin changed)
established that the upgrade is a pin + lock change with no source edits:

- Resolution: `fastmcp` 4.1.4, `fastmcp-slim` 4.1.4, `mcp` 2.3.0, `mcp-types`
  2.3.0; adds `httpx2` + `truststore`; drops `keyring` and its `jaraco-*` /
  `secretstorage` / `jeepney` helpers (FastMCP-3-only transitive deps; nothing
  in this repo imports them).
- 215/215 unit tests pass with `FastMCPDeprecationWarning` escalated to an
  error; no other warnings are emitted. `black` / `ruff` / `mypy` clean;
  `make e2e` and `make integration` pass.
- Over the real stdio subprocess, `fastmcp.Client` in its default
  `mode="auto"` negotiates `2026-07-28`; `mode="legacy"` negotiates
  `2025-11-25`. Both list all 14 tools, and a failing tool call surfaces as a
  tool error in both.

`main` currently pins `fastmcp>=3.4.10,<4` — the `<4` cap was added
deliberately in #46 to hold the major bump for this card.

## Upgrade-guide audit

Every signal from the
[FastMCP 3 → 4 upgrade guide](https://gofastmcp.com/getting-started/upgrading/from-fastmcp-3)'s
audit prompt, checked against all tracked `*.py` files (`src/`, `tests/`,
`scripts/`, `.agents/skills/*/scripts/`):

| Signal | Matches |
|---|---|
| `from mcp.server.fastmcp import FastMCP` (wrong starting version) | none |
| pydantic pin < 2.12 / Starlette < 1.0.1 / FastAPI < 0.133 | none (`pydantic>=2.12`; no Starlette/FastAPI pins) |
| Removed imports (`fastmcp.server.proxy`/`openapi`/`apps`/`tasks`/`sampling`, `fastmcp.tools.tool`, `fastmcp.resources.resource`, `fastmcp.prompts.prompt`, `fastmcp.server.auth.authorization`, `CurrentDocket`/`CurrentWorker`, `SkillsProvider`, `Cachable*`, `PromptToolMiddleware`/`ResourceToolMiddleware`) | none — only `fastmcp.FastMCP`, `fastmcp.Client`, `fastmcp.exceptions.ToolError`, `fastmcp.client.transports.StdioTransport` are imported |
| Removed server methods/kwargs (`as_proxy`, `import_server`, `mount(prefix=/as_proxy=)`, `*_tool_transformation`, `remove_tool`, `serializer=`, `exclude_args=`, `sse_read_timeout=`, `decorator_mode`, `sampling_handler=`) | none |
| Removed context methods (`ctx.sample`, `ctx.sample_step`, `ctx.list_roots`) | none — no tool takes a `Context` |
| `ctx.elicit(...)` | none |
| `except httpx.` / custom `httpx` clients handed to FastMCP | none — no `httpx` import anywhere |
| `Middleware.on_initialize`, `ctx.set_state`, `on_message` middleware | none — no middleware |
| camelCase field reads (`inputSchema`, `isError`, `structuredContent`, `mimeType`, `nextCursor`, `serverInfo`, …) | none |
| Resource-not-found code `-32002`, templated resources | none — tools only |
| OAuth / `issuer_url` | none — stdio, no auth |
| `Client("server.py")` bare-string transport | none — `Client(mcp)` (in-process `FastMCP` object) and `Client(StdioTransport(...))` only |
| Background tasks (`task=True`, `TaskConfig`) | none |
| `McpError(ErrorData(...))` construction | none |

Result: no findings to fix. The warnings-as-errors filter below keeps it that
way as code evolves.

## Design

1. **Pin.** `pyproject.toml`: `"fastmcp>=3.4.10,<4"` → `"fastmcp>=4.1.4,<5"`,
   keeping #46's major-version-cap convention (dependabot is limited to
   minor/patch updates, so the cap is the deliberate gate for the next major).
   `mcp` stays transitive — no direct dependency, since no code imports it.
   Re-lock with `uv lock`.
2. **Deprecations fail the suite.** `[tool.pytest.ini_options]` gains
   `filterwarnings = ["error::fastmcp.exceptions.FastMCPDeprecationWarning"]`.
   (The class lives in `fastmcp._warnings` but is re-exported from
   `fastmcp.exceptions`, which is the stable path pytest resolves.) It applies
   to unit, e2e, and integration runs alike, so a future change that leans on
   the camelCase bridge or another deprecated surface fails CI instead of
   warning silently.
3. **Both protocol eras are tested end to end.** `tests/test_e2e_server.py`'s
   stdio smoke test is parametrized over `Client` mode — `"auto"` asserting the
   negotiated protocol version is `2026-07-28`, `"legacy"` asserting
   `2025-11-25` — and each still asserts the full 14-tool set. This guards the
   card's "older clients keep working" claim, which nothing else exercises:
   real MCP hosts (Claude Code, Claude Desktop) may still connect on the
   handshake era. The exact `Client` attribute exposing the negotiated version
   is confirmed during implementation (the probe found it on the client
   object in auto mode and on the initialize result in legacy mode).
4. **Docs.** `AGENTS.md`'s architecture intro: "FastMCP v3 stdio server" →
   "FastMCP v4 (MCP Python SDK v2) stdio server", plus one sentence that the
   server serves both the `2026-07-28` and handshake (≤ `2025-11-25`) protocol
   eras, negotiated per connection. README has no version reference — no
   change. Dated historical specs/plans and existing `CHANGELOG.md` entries are
   left as written; `CHANGELOG.md` gets a new entry at build-from-issue's
   changelog step.

## Out of scope

- Any new v4 feature: interactive tools / write approval (#45), extensions,
  background tasks, `show_banner` tweaks.
- MCP Inspector v2 Makefile targets and doc rewrites (#44).
- Revisiting the `ynab` SDK `update_transactions` workaround now that #46 moved
  `ynab` to 4.4.1 — unrelated to this card.

## Testing

- `make pr_check` (lint + unit tests, with the new warnings filter active).
- `make e2e` (both protocol eras over the real stdio subprocess).
- `make integration`.
- Live pre-merge check: the server is launched and connected to from a real
  MCP host (see the runbook in the PR) — optional given the probe, but cheap.
