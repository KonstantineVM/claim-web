#!/usr/bin/env bash
# SessionEnd hook for CLAIM-WEB.
# Records a session summary to .claude/session-log/ for institutional memory.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR"

log_dir=".claude/session-log"
mkdir -p "$log_dir"

session_id="${CLAUDE_SESSION_ID:-unknown}"
ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
date_str=$(date -u +"%Y-%m-%d")

# Compose a short session record.
{
    echo "## $ts"
    echo "Session ID: $session_id"
    echo ""

    # Commits made this session, if any (best-effort heuristic: commits in last 24h).
    if [ -d .git ]; then
        commits=$(git log --since='24 hours ago' --oneline | head -5)
        if [ -n "$commits" ]; then
            echo "Recent commits (last 24h):"
            echo "$commits" | sed 's/^/  /'
            echo ""
        fi
    fi

    # Files changed since last session end.
    last_session_marker=".claude/session-log/.last_session_end"
    if [ -f "$last_session_marker" ] && [ -d .git ]; then
        last=$(cat "$last_session_marker")
        if [ -n "$last" ]; then
            changed=$(git diff --name-only "$last" 2>/dev/null | head -10)
            if [ -n "$changed" ]; then
                echo "Files changed since last session end:"
                echo "$changed" | sed 's/^/  /'
                echo ""
            fi
        fi
    fi
    if [ -d .git ]; then
        git rev-parse HEAD 2>/dev/null > "$last_session_marker" || true
    fi

    # Clean up Stop-counter file for this session.
    counter_file="${TMPDIR:-/tmp}/claimweb_stop_counter_${session_id}"
    [ -f "$counter_file" ] && rm -f "$counter_file"

    echo "---"
    echo ""
} >> "$log_dir/$date_str.md"

exit 0
