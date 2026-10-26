# FastMCP 4 Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the server from `fastmcp` 3.x / MCP SDK v1 to `fastmcp` 4.x / MCP SDK v2 with no source changes, proven on both protocol eras.

**Architecture:** A pin + lock change. An e2e test parametrized over `Client` mode pins both negotiated protocol eras over the real stdio subprocess; a pytest `filterwarnings` entry fails the suite on any FastMCP deprecation; `AGENTS.md` is updated.

**Tech Stack:** Python 3.13, `uv`, `fastmcp` 4.1.x, `mcp` 2.x (transitive), pytest.

**Spec:** `docs/superpowers/specs/2026-10-26-fastmcp-4-upgrade-design.md`

## Global Constraints

- Pin exactly `"fastmcp>=4.1.4,<5"` in `[project].dependencies`; no direct `mcp` dependency.
- Warnings filter exactly `"error::fastmcp.exceptions.FastMCPDeprecationWarning"`.
- Modern era string `"2026-07-28"`; handshake/legacy era string `"2025-11-25"`.
- No new v4 features (#45), no Inspector targets (#44), no source changes under `src/` unless a test forces one.
- Run Python only via `uv` (`uv run …`, `uv lock`).

## Review Focus

1. A real MCP host (Claude Code / Claude Desktop) connecting on whichever era it supports — expected: all 14 tools listed, tool calls work. Not automatable here; covered by the PR's live runbook.
2. Startup output on stdio — expected: FastMCP 4's banner/logs go to stderr only, never stdout (stdout corruption breaks the protocol). Pinned implicitly by the e2e handshake succeeding on both eras (Task 1).
3. A failing YNAB call on a modern-era connection — expected: still a tool error carrying YNAB's detail. Pinned by existing in-process `Client(mcp)` tests (which now negotiate the modern era by default) — re-run in Task 1 Step 5.
4. A future edit leaning on a deprecated FastMCP surface (e.g. reading `result.isError`) — expected: the suite fails, not warns. Pinned by Task 2's filter + its throwaway verification step.
5. Lockfile conflict with in-flight PR #47 (`amazon-orders` 5.2.0) — expected: whichever merges second re-runs `uv lock`; no code conflict. Handled at merge time, not by a test.

---

### Task 1: Upgrade to fastmcp 4 and pin both protocol eras end to end

**Files:**
- Modify: `tests/test_e2e_server.py` (helper + test at lines 10-65)
- Modify: `pyproject.toml:10`
- Modify: `uv.lock` (regenerated)

**Interfaces:**
- Consumes: `fastmcp.Client(transport, mode=...)` (4.x; `mode: Literal["auto", "legacy"]`, default `"auto"`), `Client.protocol_version -> str | None` (era-neutral negotiated version).
- Produces: `_list_tools_and_protocol(transport, mode) -> tuple[set[str], str | None]` (test-local helper).

- [ ] **Step 1: Write the failing test** — replace the helper and parametrize the test in `tests/test_e2e_server.py`:

```python
async def _list_tools_and_protocol(
    transport: StdioTransport, mode: str
) -> tuple[set[str], str | None]:
    """List every tool name, and the negotiated protocol version, over stdio.

    Parameters
    ----------
    transport : fastmcp.client.transports.StdioTransport
        A transport for the real `uv run ynab-mcp` subprocess.
    mode : str
        The ``fastmcp.Client`` connect mode: ``"auto"`` negotiates the modern
        ``2026-07-28`` protocol era, ``"legacy"`` pins the handshake era.

    Returns
    -------
    tuple[set[str], str | None]
        Every registered tool's name, and the protocol version the
        connection negotiated.
    """
    async with Client(transport, mode=mode) as client:
        tools = await client.list_tools()
        return {tool.name for tool in tools}, client.protocol_version


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("mode", "expected_protocol"),
    [("auto", "2026-07-28"), ("legacy", "2025-11-25")],
)
def test_uv_run_ynab_mcp_stdio_server_lists_expected_tools(
    mode: str, expected_protocol: str
) -> None:
    """The real stdio subprocess lists all 14 tools on both protocol eras.

    (keep the existing docstring body, then add:)
    Parametrized over both MCP protocol eras: ``auto`` negotiates the modern
    ``2026-07-28`` revision, ``legacy`` the handshake era that MCP hosts
    without modern support still speak -- the server must serve both.
    """
    transport = ...  # unchanged
    tool_names, protocol = asyncio.run(_list_tools_and_protocol(transport, mode))
    assert protocol == expected_protocol
    assert tool_names == {...}  # unchanged 14-tool set
```

- [ ] **Step 2: Run test to verify it fails (still on fastmcp 3.x)**

Run: `uv run pytest -m e2e -v --tb=short`
Expected: FAIL — `TypeError` on the unknown `mode=` kwarg (3.x `Client` has no `mode`).

- [ ] **Step 3: Bump the pin and re-lock**

`pyproject.toml`: `"fastmcp>=3.4.10,<4",` → `"fastmcp>=4.1.4,<5",`, then:

```bash
uv lock && uv sync
grep -A1 -E '^name = "(fastmcp|mcp)"$' uv.lock
```
Expected: `fastmcp` 4.1.x and `mcp` 2.x.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -m e2e -v --tb=short`
Expected: 2 passed (`[auto-2026-07-28]`, `[legacy-2025-11-25]`).

- [ ] **Step 5: Full regression**

Run: `make pr_check && make integration`
Expected: lint clean; 215 unit tests pass; integration passes.

- [ ] **Step 6: Commit + push**

```bash
git add pyproject.toml uv.lock tests/test_e2e_server.py
git commit -m "deps: upgrade to fastmcp 4 / MCP SDK v2; e2e both protocol eras (#43)"
git push
```

### Task 2: Fail the suite on FastMCP deprecations; update AGENTS.md

**Files:**
- Modify: `pyproject.toml` (`[tool.pytest.ini_options]`)
- Modify: `AGENTS.md:39`

**Interfaces:**
- Consumes: `fastmcp.exceptions.FastMCPDeprecationWarning` (4.x re-export).
- Produces: nothing code-facing.

- [ ] **Step 1: Prove a deprecation currently only warns (RED)** — throwaway file `tests/test_tmp_deprecation_probe.py`:

```python
import warnings

from fastmcp.exceptions import FastMCPDeprecationWarning


def test_deprecation_is_fatal() -> None:
    warnings.warn("probe", FastMCPDeprecationWarning, stacklevel=1)
```

Run: `uv run pytest tests/test_tmp_deprecation_probe.py -o addopts="" -q`
Expected: PASS with a warning (i.e. not fatal yet).

- [ ] **Step 2: Add the filter** to `[tool.pytest.ini_options]` in `pyproject.toml`:

```toml
filterwarnings = ["error::fastmcp.exceptions.FastMCPDeprecationWarning"]
```

- [ ] **Step 3: Verify it is now fatal (GREEN), then delete the probe**

Run: `uv run pytest tests/test_tmp_deprecation_probe.py -o addopts="" -q`
Expected: FAIL with `FastMCPDeprecationWarning: probe`.
Then: `rm tests/test_tmp_deprecation_probe.py`.

- [ ] **Step 4: Update AGENTS.md** — line 39 `A FastMCP v3 stdio server wrapping the official \`ynab\` PyPI client.` → `A FastMCP v4 (MCP Python SDK v2) stdio server wrapping the official \`ynab\` PyPI client`, and add after the intro paragraph: "It serves both MCP protocol eras, negotiated per connection — the modern `2026-07-28` revision and the handshake era (≤ `2025-11-25`) — and `pyproject.toml`'s pytest config turns any `FastMCPDeprecationWarning` into a test failure." (Re-flow to the file's ~78-col wrap.)

- [ ] **Step 5: Full suite**

Run: `make pr_check && make e2e && make integration`
Expected: all green.

- [ ] **Step 6: Commit + push**

```bash
git add pyproject.toml AGENTS.md
git commit -m "test: fail on FastMCP deprecations; document FastMCP 4 (#43)"
git push
```
