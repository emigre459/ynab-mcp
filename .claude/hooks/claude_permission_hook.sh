#!/bin/bash

# Forward pre-approved Bash permissions from settings.json layers (user,
# project, local) to PreToolUse so subagents don't re-prompt for commands
# the parent has already approved.

INPUT_JSON=$(cat)

EVENT_NAME=$(echo "$INPUT_JSON" | jq -r '.hook_event_name // empty')
TOOL_NAME=$(echo "$INPUT_JSON" | jq -r '.tool_name // empty')

# Defensive: matcher in settings.json should already restrict us to Bash
# PreToolUse, but bail cleanly if something else slips through. No JSON
# output -> Claude Code's normal permission flow runs.
if [ "$EVENT_NAME" != "PreToolUse" ] || [ "$TOOL_NAME" != "Bash" ]; then
    exit 0
fi

REQUESTED_CMD=$(echo "$INPUT_JSON" | jq -r '.tool_input.command // empty')

CONFIG_FILES=(
    "$HOME/.claude/settings.json"
    ".claude/settings.json"
    ".claude/settings.local.json"
)

for FILE in "${CONFIG_FILES[@]}"; do
    [ -f "$FILE" ] || continue

    # Strip the Bash(...) wrapper to get the raw command pattern
    ALLOWED_CMDS=$(jq -r '.permissions.allow[]? // empty' "$FILE" \
        | grep -E '^Bash\(.+\)$' \
        | sed -E 's/^Bash\((.+)\)$/\1/')

    while IFS= read -r PATTERN; do
        [ -z "$PATTERN" ] && continue

        if [[ "$PATTERN" == *"*" ]]; then
            # Trailing-wildcard rule: e.g. "git *" matches "git status"
            CLEAN_PATTERN="${PATTERN%\*}"
            if [[ "$REQUESTED_CMD" == "$CLEAN_PATTERN"* ]]; then
                printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","permissionDecisionReason":"Hook matched allowed pattern: Bash(%s)"}}\n' "$PATTERN"
                exit 0
            fi
        else
            # Exact-match rule
            if [ "$REQUESTED_CMD" = "$PATTERN" ]; then
                printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","permissionDecisionReason":"Hook matched exact pattern: Bash(%s)"}}\n' "$PATTERN"
                exit 0
            fi
        fi
    done <<< "$ALLOWED_CMDS"
done

# No pattern matched -> defer to Claude Code's normal permission flow
exit 0
