---
description: Set GH-native blocked-by relationships (not just body text) for issue prereqs. The REST dependencies API needs the integer database ID, not the issue number.
alwaysApply: true
---

# GitHub issue dependencies (blocked-by)

When a follow-up issue has hard prerequisites, set a **GH-native blocked-by
relationship in addition to** mentioning the prereq in the body. Body text alone
is not enforceable — readers miss it, boards don't surface it, the kanban won't gate.

## Setting the relationship (GraphQL)

```bash
# Get node IDs first
gh api graphql -f query='{ repository(owner:"<owner>", name:"<repo>") { issue(number: N) { id } } }'

# Add the blocked-by (arg is blockingIssueId; payload field is blockingIssue)
gh api graphql -f query='
mutation {
  addBlockedBy(input: {
    issueId: "<NODE_ID_OF_BLOCKED_ISSUE>",
    blockingIssueId: "<NODE_ID_OF_BLOCKING_ISSUE>"
  }) { issue { number title } }
}'
```
Removal: `removeBlockedBy` with the same shape. Parent-child (distinct from
blocking): `addSubIssue`.

## REST dependencies API needs the DATABASE ID, not the issue number

`POST /repos/{owner}/{repo}/issues/{n}/dependencies/blocked_by` expects `issue_id`
to be the internal **database ID** (a large integer like `4441387262`), not the
human issue number. Passing the issue number silently matches an unrelated issue
from another repo with that database ID. Always fetch it first:

```bash
DB_ID=$(gh api repos/<owner>/<repo>/issues/{number} --jq '.id')
gh api repos/<owner>/<repo>/issues/{target}/dependencies/blocked_by -X POST -F issue_id=$DB_ID
# DELETE uses the database ID in the path too:
gh api repos/<owner>/<repo>/issues/{target}/dependencies/blocked_by/$DB_ID -X DELETE
```

## Always

- Keep the prereq explicit in body text under a "Blocked by" section too.
- Use `- [ ] #N` task-list syntax in **parent** bodies for tracked subtasks
  (tracking ≠ blocking).
- Verify the dependency landed by re-fetching the issue, not by trusting the
  mutation response.
