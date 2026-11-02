# Live test kit — approval prompt before YNAB writes (issue #45)

Run from this branch's checkout (`issue-45`). **Use your test budget only**:
every scenario below really writes when approved. Each scenario that creates
data also removes it.

## What this proves

Tests already cover the logic on both protocol eras, and the E2E runs the real
subprocess with a dummy token. Only you can check the rest:

- how the prompt actually looks in Claude Code and MCP Inspector;
- whether **Claude Code can show these prompts at all**. If it can't, writes from
  Claude Code are refused until you set `YNAB_REQUIRE_WRITE_APPROVAL=false`;
- that names, amounts, and writes are right against real YNAB data.

## 1. Configure

In `.env` (`cp .env.example .env` if you have none):

```bash
YNAB_PAT=<your token>
YNAB_DEFAULT_BUDGET_ID=<test budget id>
YNAB_READ_ONLY=false
YNAB_REQUIRE_WRITE_APPROVAL=true
```

Have the test budget open in YNAB's web app so you can confirm each write. You'll
also need one account id and two category ids; `list-accounts` and
`list-categories` return them.

## 2. Claude Code (the decisive check)

Copy `.mcp.json.example` to `.mcp.json` with `--directory` set to this checkout,
restart Claude Code, and confirm `ynab` is connected with `/mcp`. Then ask, one
at a time, in a fresh session:

| # | Ask Claude | Answer the prompt | Pass when |
|---|---|---|---|
| C1 | "Create a $1.23 outflow in the test budget on today's date, payee 'Approval Test', on account <name>." | Read it, then **decline** | Prompt shows the account's **name** and `-$1.23 (outflow)`; Claude reports "Not applied"; nothing new in YNAB |
| C2 | "Try that again." | **Approve** | Transaction appears in YNAB |
| C3 | "Change that transaction's category to <name>." | **Approve** | Prompt header identifies the transaction; shows `old  →  new` by name; YNAB updated |
| C4 | "Delete that transaction." | **Approve** | Prompt identifies it; gone from YNAB |

**If no prompt appears and Claude reports "this client can't show approval
prompts":** that's the fail-closed path working, and it answers the open question.
Tell me, and we'll document that Claude Code needs the opt-out.

## 3. MCP Inspector v2

Run I1 on the modern era, then repeat I1 and I4-I6 on the handshake era:

```bash
make inspect                       # 2026-07-28
make inspect INSPECTOR_ERA=legacy  # handshake era (2025-11-25)
```

Connect and open **Tools**. Run these, with ids from `list-*`:

| # | Tool and arguments | Answer | Pass when |
|---|---|---|---|
| I1 | `manage-budgeted-amount`: `operation=assign`, `month=current`, `category_id=<id>`, `amount=1000` | **Decline** | Prompt shows `<name>, <month>:  $X now  →  $1.00`; result says "Not applied"; YNAB unchanged |
| I2 | `manage-budgeted-amount`: `operation=move`, `month=current`, `from_category_id=<id>`, `to_category_id=<id>`, `amount=1000` | **Approve** | Both totals in YNAB change as the prompt said |
| I3 | Same as I2, with the two ids swapped | **Approve** | Restores the original totals |
| I4 | `manage-scheduled-transaction`: `operation=create`, `account_id=<id>`, `date=<a future date>`, `amount=-1000`, `frequency=monthly`, `memo=keep me` | **Approve** | Appears under scheduled transactions in YNAB, with the memo |
| I5 | `manage-scheduled-transaction`: `operation=update`, same fields and `scheduled_transaction_id=<id from I4>`, **without** `memo` | **Approve** | Prompt says `Memo:  keep me  →  (cleared)`, and the memo is really gone in YNAB. If it's still there, tell me: the prompt overstates |
| I6 | `manage-scheduled-transaction`: `operation=delete`, `scheduled_transaction_id=<id from I4>` | **Approve** | Prompt identifies it; gone from YNAB |

Note how Inspector renders multi-line text and the yes/no field.

## 4. Both eras from a terminal

This script drives a create and delete on each era against real data, with a
pause that makes the "changed in YNAB" refusal easy to trigger. Save it as
`.context/try_approval.py`, and set `ACCOUNT_ID` first:

```python
import asyncio, sys
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult
from fastmcp.client.transports import StdioTransport

ACCOUNT_ID = "<account id>"

async def ask(message, response_type, params, context):
    print(f"\n----- PROMPT -----\n{message}\n------------------")
    if input("Approve? [y/N] ").strip().lower() == "y":
        return response_type(value=True)
    return ElicitResult(action="decline")

async def main(mode):
    async with Client(
        StdioTransport("uv", ["run", "ynab-mcp"]), mode=mode, elicitation_handler=ask
    ) as client:
        print("Protocol:", client.protocol_version)
        created = await client.call_tool("bulk-manage-transactions", {"operations": [
            {"action": "create", "account_id": ACCOUNT_ID, "date": "2026-11-01",
             "amount": -1230, "payee_name": "Approval Test", "memo": "#45 live test"}
        ]}, raise_on_error=False)
        print(created.content[0].text)
        if created.is_error:
            return
        txn = created.structured_content["result"][0]["id"]
        input("Now edit that transaction's amount in YNAB for T3, or just press enter: ")
        deleted = await client.call_tool("bulk-manage-transactions", {
            "operations": [{"action": "delete", "id": txn}]}, raise_on_error=False)
        print(deleted.content[0].text)

asyncio.run(main(sys.argv[1]))
```

| # | Command | Do | Pass when |
|---|---|---|---|
| T1 | `uv run python .context/try_approval.py auto` | Approve both | Prints `Protocol: 2026-07-28`; transaction created then deleted |
| T2 | `uv run python .context/try_approval.py legacy` | Approve both | Prints `Protocol: 2025-11-25`; same result |
| T3 | Either command | Approve the create; run to the pause; at the delete **prompt**, change the amount in YNAB's web app, wait for it to save, then approve | "Not applied — transaction … changed in YNAB". Delete the test transaction by hand |

## 5. Opt-out

Set `YNAB_REQUIRE_WRITE_APPROVAL=false`, and rerun T1. **Pass:** no prompts, both
writes happen. Set it back to `true` afterwards.

## Pass / fail

**Pass:** every row above behaves as stated, and you'd be comfortable approving
from the prompt without opening YNAB.

If something fails, the first things to check:

- `YNAB_READ_ONLY` error → `.env` still has it `true`, or the client wasn't restarted.
- Raw ids instead of names → the lookups failed, often a 429: YNAB allows about
  200 requests an hour.
- "the arguments changed" on approval → the client altered arguments between
  rounds; tell me which client.

Send me: Claude Code's result for C1 (a screenshot is ideal), any failing row, and
anything about the prompt you'd still find hard to read.
