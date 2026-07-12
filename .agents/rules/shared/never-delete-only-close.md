---
description: Remove issues/PRs by closing with an explanatory comment — never gh issue delete or REST DELETE. Preserves the audit trail.
alwaysApply: true
---

# Never delete — close with a comment

When the right move is to remove an issue or PR (duplicate, stale, superseded, no
longer relevant), **close it with an explanatory comment — never delete it.**

**Why:** Deletion loses the audit trail (original idea, discussion, abandonment
reasoning, inbound links). Closure preserves it and can link forward to whatever
superseded it.

**How to apply**
- Issue: `gh issue comment <n> --body "<reason + link(s) to superseding work>"`
  then `gh issue close <n>`. Never `gh issue delete`, never `DELETE /repos/.../issues/...`.
- PR: close with a comment naming the reason and any superseding PR/branch instead
  of reflexively deleting the branch. Branch cleanup happens later via `/clean_gone`
  once the remote is gone.
- The closing comment should be self-documenting — name + link the superseding
  work and state the reason in one sentence.
- Treat colloquial "remove"/"get rid of" as "close with comment" unless the user
  explicitly says "delete" *and* justifies why deletion (not closure) is right.
- Never auto-close even at high confidence — the user gives the final yes/no.
