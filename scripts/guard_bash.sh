#!/usr/bin/env bash
# PreToolUse hook for Bash commands. Blocks dangerous patterns.
# Exit 2 blocks the tool call and sends stderr back to Claude.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Read the tool input from stdin (JSON).
input=$(cat)
command=$(echo "$input" | jq -r '.tool_input.command // ""')

# Patterns to block outright. These are dangerous-and-unrecoverable, not just risky.
block_patterns=(
    'rm[[:space:]]+-rf[[:space:]]+/'             # rm -rf /
    'rm[[:space:]]+-rf[[:space:]]+\$HOME'        # rm -rf $HOME
    'rm[[:space:]]+-rf[[:space:]]+~'             # rm -rf ~
    ':\(\)\{[[:space:]]*:\|:&[[:space:]]*\};:'   # fork bomb
    'chmod[[:space:]]+-R[[:space:]]+777[[:space:]]+/'  # recursive 777 on /
    'mkfs\.'                                     # filesystem creation
    'dd[[:space:]]+if=.*of=/dev/[shn]d[a-z]'     # writing to raw devices
    '>[[:space:]]*/dev/sda'                      # ditto
    'curl.*\|[[:space:]]*sh'                     # curl pipe to shell (un-vetted)
    'wget.*\|[[:space:]]*sh'                     # wget pipe to shell
)

for pattern in "${block_patterns[@]}"; do
    if echo "$command" | grep -qE "$pattern"; then
        echo "BLOCKED: command matches dangerous pattern: $pattern" >&2
        echo "If this is intentional, the user must run it manually outside Claude Code." >&2
        exit 2
    fi
done

# Block destructive git operations.
# Note: --force-with-lease is intentionally NOT blocked — it is the safe force-push
# variant that fails if the remote has diverged beyond the local fetch, preventing
# accidental history loss. Only bare --force and -f are blocked.
if echo "$command" | grep -qE 'git[[:space:]]+(push[[:space:]]+((-f|--force)([[:space:]]|$))|reset[[:space:]]+--hard[[:space:]]+HEAD[[:space:]]*~)'; then
    # Force push and hard reset can lose work. Block, require explicit user confirmation.
    echo "BLOCKED: destructive git operation. Force-push and hard-reset can lose work." >&2
    echo "Discuss with the user before performing this. They can run it manually if needed." >&2
    exit 2
fi

# Block paid-aggregator URL fetches.
if echo "$command" | grep -qiE '(capitaliq|spcapitaliq|spglobal\.com.*premium|moodys\.com.*creditview|lcdcomps|leveragedcommentary)'; then
    echo "BLOCKED: paid aggregator URL detected." >&2
    echo "Per CLAUDE.md standing rule: origin data only. Use the free primary source instead." >&2
    exit 2
fi

# Block commits without going through the precommit gate.
# (Direct git commit is allowed; this is just a soft reminder via stderr that doesn't block.)
if echo "$command" | grep -qE '^git[[:space:]]+commit\b' && ! echo "$command" | grep -qE 'precommit|gate'; then
    echo "Reminder: scripts/precommit_gate.sh should be run before commits. Continuing." >&2
    # exit 0 — don't block, just note.
fi

exit 0
