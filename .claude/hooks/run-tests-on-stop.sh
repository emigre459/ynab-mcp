#!/bin/bash
# Hook: runs at the end of every Claude turn.
# Formats + runs tests for whichever stack is active, only when relevant
# source files changed this session.

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Include changes already COMMITTED on this branch (vs the base branch), not just
# uncommitted ones — otherwise the guard is bypassed exactly when you follow the
# checkpoint-commits rule and commit mid-turn (the working tree is then clean).
base=$(git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD main 2>/dev/null || true)
changed=$(
  {
    [ -n "$base" ] && git diff --name-only "$base" HEAD 2>/dev/null  # committed on this branch
    git diff --name-only HEAD 2>/dev/null                            # unstaged
    git diff --name-only --cached 2>/dev/null                        # staged
    git ls-files --others --exclude-standard 2>/dev/null             # untracked
  } | sort -u
)
[ -z "$changed" ] && exit 0

run_gate() { # $1 = subdir ("" for root), $2 = grep pattern
  echo "$changed" | grep -qE "$2" || return 0
  echo "Source changed — formatting and running tests..."
  if [ -n "$1" ]; then make -C "$1" format && make -C "$1" tests || return 1
  else make format && make tests || return 1; fi
}

if [ -d stacks ]; then
  # Pre-init template repo: exercise both stacks + machinery as relevant.
  rc=0
  run_gate "stacks/python" '^stacks/python/.*\.py$' || rc=2
  run_gate "stacks/react" '^stacks/react/.*\.(ts|tsx)$' || rc=2
  if echo "$changed" | grep -qE '^(scripts|tests/template)/'; then
    # Format machinery first (parity with the stack branches' `make format`) so a
    # formatting slip doesn't pass this hook yet fail CI's `black --check`. Route
    # through make like the stack branches — never raw commands.
    make machinery_format && make machinery_tests || rc=2
  fi
  exit $rc
elif [ -f package.json ]; then
  run_gate "" '\.(ts|tsx)$' || exit 2
else
  run_gate "" '\.py$' || exit 2
fi
exit 0
