#!/usr/bin/env bash
# UserPromptSubmit hook for CLAIM-WEB.
# When the user submits a "continue / what's next / resume" style prompt, inject the current TODO Now item silently.
# This prevents Claude from drifting to ad-hoc tasks when the user clearly means "pick up where we left off."

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR"

# Read the prompt from stdin (JSON, with the prompt at .prompt).
input=$(cat)
prompt=$(echo "$input" | jq -r '.prompt // ""')

# Trigger only on resumption-style prompts to keep this hook unobtrusive.
if echo "$prompt" | grep -qiE '^(continue|resume|what.?s next|next|pick up|carry on|keep going|proceed)\b'; then
    if [ -f TODO.md ]; then
        now=$(awk '/^## Now/,/^## Next/' TODO.md | head -20)
        if [ -n "$now" ]; then
            jq -n --arg ctx "Resumption detected. The current Now item from TODO.md:\n\n$now" '{
              "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": $ctx
              }
            }'
            exit 0
        fi
    fi
fi

# Default: no-op.
exit 0
