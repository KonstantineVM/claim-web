#!/usr/bin/env bash
# PreToolUse hook for Write/Edit/MultiEdit. Blocks code that introduces paid-aggregator dependencies.
# Exit 2 blocks the tool call and surfaces stderr to Claude.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Read the tool input from stdin (JSON).
input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')

# Get the proposed content. For Write, it's .tool_input.content. For Edit, it's .tool_input.new_string.
# For MultiEdit, it's an array under .tool_input.edits[].new_string.
content=$(echo "$input" | jq -r '.tool_input.content // .tool_input.new_string // ([.tool_input.edits[]?.new_string] | join("\n")) // ""')

# Only check source-code files. Markdown notes can reference paid aggregators as context.
case "$file_path" in
    *.py|*.toml|*.yaml|*.yml|*.json|*.cfg|*.ini|*.sh)
        ;;
    *)
        exit 0
        ;;
esac

# Forbidden imports / strings in source files.
forbidden=(
    'capitaliq'
    'spcapitaliq'
    'spglobal.*premium'
    'creditview'
    'moodys.*api'                    # moodys.com API access
    'leveragedcommentary'
    'lcdcomps'
    'preqin'
    'pitchbook'
    'refinitiv.*eikon'
    'bloomberg.*terminal'
    'factset'
)

violations=()
for pattern in "${forbidden[@]}"; do
    if echo "$content" | grep -qiE "$pattern"; then
        violations+=("$pattern")
    fi
done

if [ ${#violations[@]} -gt 0 ]; then
    echo "BLOCKED: paid-aggregator dependency detected in $file_path" >&2
    echo "Matched patterns: ${violations[*]}" >&2
    echo "Per CLAUDE.md and project plan: origin data only. SEC EDGAR, FRB Z.1, FHLB Office of Finance, NAIC state portals, BMA registers, FIO, OFR are the universe of permitted sources." >&2
    echo "If you need data that is genuinely only available from a paid aggregator, surface it to the user before introducing the dependency." >&2
    exit 2
fi

exit 0
