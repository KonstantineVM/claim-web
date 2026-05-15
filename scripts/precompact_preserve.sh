#!/usr/bin/env bash
# PreCompact hook for CLAIM-WEB.
# Compaction summarizes the conversation when context is full. Some details
# matter so much (current Phase, current Now item, validation state) that we
# explicitly preserve them by emitting them as context just before compaction runs.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR"

input=$(cat)

# Build a preservation context. Compose from CHANGELOG, TODO, and the validation status if any.
preserve=""

# Always preserve the current Now and Next from TODO.md.
if [ -f TODO.md ]; then
    now_next=$(awk '/^## Now/,/^## Backlog/' TODO.md | head -40)
    preserve+="## Preserved across compaction: current TODO Now/Next\n\n$now_next\n\n"
fi

# Always preserve the most recent CHANGELOG entry — what was just done.
if [ -f CHANGELOG.md ]; then
    recent=$(awk '/^### / { if (seen) exit; seen=1 } seen' CHANGELOG.md | head -30)
    preserve+="## Preserved across compaction: most recent CHANGELOG entry\n\n$recent\n\n"
fi

# Preserve the validation status — has each historical episode been retrodicted yet?
if [ -f docs/PHASE_GATES.md ]; then
    gate_status=$(grep -E '^- \[' docs/PHASE_GATES.md | head -10)
    preserve+="## Preserved across compaction: phase-gate status\n\n$gate_status\n\n"
fi

# Reminder about hard rules.
preserve+="## Preserved standing rules (from CLAUDE.md)\n\n- Conservation laws are invariants, enforced by hooks.\n- Origin data only; no paid aggregators.\n- Both maximum-entropy and minimum-density reconstructions are run.\n- Historical validation gates deployment.\n- Commit and push after every meaningful unit of work; CHANGELOG/TODO stay in sync.\n"

# PreCompact uses additionalContext same as SessionStart in Claude Code 2.1+.
jq -n --arg ctx "$preserve" '{
  "hookSpecificOutput": {
    "hookEventName": "PreCompact",
    "additionalContext": $ctx
  }
}'

exit 0
