#!/usr/bin/env bash
# SessionStart hook for CLAIM-WEB.
# Injects current project state as additionalContext for the new session.
# Per https://code.claude.com/docs/en/hooks — SessionStart stdout is added as context that Claude can see.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR"

# Build a compact state summary. Total budget: ~200 lines or so.
context=""

# 1. Git branch and status (truncated)
if [ -d .git ]; then
    branch=$(git branch --show-current 2>/dev/null || echo "unknown")
    short_status=$(git status --short 2>/dev/null | head -10 || true)
    context+="## Git\nBranch: $branch\n"
    if [ -n "$short_status" ]; then
        context+="Uncommitted changes (first 10):\n$short_status\n"
    else
        context+="Working tree clean.\n"
    fi
    context+="\n"
fi

# 2. The first 30 lines of TODO.md so the Now/Next is immediately visible
if [ -f TODO.md ]; then
    context+="## Current TODO (top of file)\n"
    context+="$(head -30 TODO.md)\n\n"
fi

# 3. The most recent CHANGELOG entry (between the first ### heading and the next one)
if [ -f CHANGELOG.md ]; then
    context+="## Most recent CHANGELOG entry\n"
    context+="$(awk '/^### / { if (seen) exit; seen=1 } seen' CHANGELOG.md | head -40)\n\n"
fi

# 4. Phase gate status if present
if [ -f docs/PHASE_GATES.md ]; then
    context+="## Phase gates (see docs/PHASE_GATES.md for full)\n"
    context+="$(grep -E '^- \[' docs/PHASE_GATES.md | head -10)\n\n"
fi

# 5. Reminder about CLAUDE.md
context+="Read CLAUDE.md for standing rules. The full project plan is at docs/CLAIM_WEB_PROJECT_PLAN.md.\n"

# Emit as JSON additionalContext (Claude Code 2.1+ silent injection)
jq -n --arg ctx "$context" '{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": $ctx
  }
}'

exit 0
