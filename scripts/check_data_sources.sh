#!/usr/bin/env bash
# Check the codebase for paid-aggregator references.
# Mirrors the PreToolUse hook check but runs across the full codebase, not single files.
# Used by the precommit gate.

set -uo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR"

# Patterns to search for. Same as the PreToolUse hook.
patterns=(
    'capitaliq'
    'spcapitaliq'
    'creditview'
    'moodys\.com.*api'
    'leveragedcommentary'
    'lcdcomps'
    'preqin'
    'pitchbook'
    'refinitiv.*eikon'
    'bloomberg.*terminal'
    'factset'
)

violations=0
for pattern in "${patterns[@]}"; do
    # Only search source-code files. Don't search docs (which legitimately mention these as context).
    matches=$(grep -rIniE "$pattern" \
        --include='*.py' \
        --include='*.toml' \
        --include='*.yaml' \
        --include='*.yml' \
        --include='*.json' \
        --include='*.sh' \
        --exclude-dir='.git' \
        --exclude-dir='node_modules' \
        --exclude-dir='.venv' \
        --exclude-dir='.claude/session-log' \
        . 2>/dev/null || true)
    if [ -n "$matches" ]; then
        echo "FAIL: paid-aggregator reference found:" >&2
        echo "  pattern: $pattern" >&2
        echo "$matches" | sed 's/^/    /' >&2
        violations=$((violations + 1))
    fi
done

if [ "$violations" -gt 0 ]; then
    echo "" >&2
    echo "Per CLAUDE.md and project plan: origin data only." >&2
    echo "Use free primary sources (SEC EDGAR, FRB Z.1, FHLB Office of Finance, NAIC, BMA, FIO, OFR)." >&2
    exit 1
fi

exit 0
