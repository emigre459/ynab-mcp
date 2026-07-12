# Gridium MCP cross-tracker routing (gridium-agent ↔ Jira GRID-10964)

Consult this file when `/plan-issues` is running in `Gridium/gridium-agent` and any candidate card touches the Gridium MCP server. If the planning session is happening in a different repo, ignore this routing — it's repo-specific to gridium-agent.

## Context

The Gridium MCP server (https://mcp.gridium.com; code at `Gridium/webapps`, path `app/mcp_server/`) lives **outside** the gridium-agent repo. Engineering-side feature requests against the MCP server are tracked in **Jira epic [GRID-10964](https://gridium.atlassian.net/browse/GRID-10964)** ("MCP Internal Feature Requests Q2 2026"; owner: Nate Lamb; due 2026-06-30). The gridium-agent GitHub kanban tracks the **client** side of any MCP-related work.

## Classification rules

When planning in gridium-agent, classify each proposed card before drafting:

* **Server-side work** → Jira story under GRID-10964. Includes: new MCP endpoints/tools, FastMCP / GoogleProvider config changes, `localconfig_mcp_server.py` edits, deploy procedures, the MCP server's own runbook/ops concerns.
* **Client-side work** → GitHub issue in `Gridium/gridium-agent`, parented under whichever gridium-agent epic fits. Includes: how gridium-agent *calls* the MCP server (bootstrap scripts, runtime client wrappers, token storage, refresh handling), Stage-1 forced profile pulls, consumer-side schema mapping.
* **Coordinated work (most cases)** → use the twin-card pattern below.

## Twin-card pattern (coordinated work)

* **GitHub card holds the full spec** — acceptance criteria, design context, blocked-by edges, scope / out-of-scope.
* **Jira card holds a terse summary** + acceptance bullets + `**Source:** [gridium-agent#N](url)` link back.
* **GitHub card body names the Jira key** (e.g., "Blocked by: GRID-XXXXX (server-side …)").
* Jira title format: action-verb + tool/concept + "on MCP server" (e.g., "Add `find_similar_buildings` tool to MCP server").
* Reporter on Jira: whoever files; the body's `**Requested by:** <name>` line names the actual requester for audit.

## Materialization (used by Phase 5 of the skill)

For each card classified as server-side under GRID-10964, create the Jira story via the Atlassian MCP tool:

```
mcp__plugin_atlassian_atlassian__createJiraIssue(
  cloudId="<gridium.atlassian.net cloud ID>",
  projectKey="GRID",
  issueTypeName="Story",
  summary="<action-verb + tool/concept + 'on MCP server'>",
  description="<terse body — Why + Acceptance bullets + **Source:** <gh-url> + **Requested by:** <name>>",
  additional_fields={"parent": {"key": "GRID-10964"}}
)
```

Cross-link bidirectionally:

* Add the Jira key to the GitHub twin card's body if a twin exists (e.g., "Blocked by: GRID-XXXXX (server-side …)"). Use `gh issue edit <n> --body-file -` to update the GH card.
* The Jira description must contain `**Source:** <gh-url>` pointing back to the twin.
* **Verify both directions are present** before declaring the step done.

## Don't

* File MCP server-side work as a GitHub issue in gridium-agent. It will sit in the wrong kanban and stall (e.g., gridium-agent#6's OAuth checkbox sat stranded for months because of this).
* File client-side gridium-agent work in Jira. Engineering doesn't want gridium-agent's internal sequencing in their queue.
* Drop the bidirectional link. A Jira card whose GitHub twin is unknown becomes orphaned at next triage.

## Reach

This routing applies to *every* /plan-issues session in gridium-agent, even when the prompt doesn't obviously touch the MCP server — surface it early in Phase 2 if any candidate cards smell server-side.
