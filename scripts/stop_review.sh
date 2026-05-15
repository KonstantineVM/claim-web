#!/usr/bin/env bash
# Stop hook for CLAIM-WEB.
# When Claude announces it's done, this hook checks whether it actually is.
# Implements the Ralph-loop pattern from https://www.anthropic.com/research/long-running-Claude
#
# Exit 0: allow stop.
# Exit 2: block stop and feed reason back to Claude (Claude continues working).
# JSON {"decision": "block", "reason": "..."} also blocks.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR"

# Read input — we don't actually need it for this hook, but consume it.
input=$(cat)

# A counter file prevents an infinite loop where Stop blocks, Claude tries to stop again, Stop blocks again, etc.
# We allow at most N consecutive Stop-blocks before giving up and letting the session end.
counter_file="${TMPDIR:-/tmp}/claimweb_stop_counter_${CLAUDE_SESSION_ID:-default}"
count=0
if [ -f "$counter_file" ]; then
    count=$(cat "$counter_file")
fi

# Cap at 3 — after 3 challenges, allow stop.
if [ "$count" -ge 3 ]; then
    rm -f "$counter_file"
    exit 0
fi

# Pre-flight checks. If any fail, the agent is not actually done.
reasons=()

# 1. Are there uncommitted changes to claimweb/, data/, docs/, tests/, or .claude/?
if [ -d .git ]; then
    important_changes=$(git status --short -- claimweb/ data/ docs/ tests/ .claude/ CHANGELOG.md TODO.md 2>/dev/null | head -5)
    if [ -n "$important_changes" ]; then
        reasons+=("Uncommitted changes in important paths:\n$important_changes\nCommit and push before stopping. Run scripts/precommit_gate.sh first.")
    fi
fi

# 2. Was CHANGELOG.md updated in this session? Look for "Modified" status.
# If files under claimweb/ or data/ changed but CHANGELOG.md was not touched, that's a missing update.
if [ -d .git ]; then
    code_changed=$(git diff --name-only HEAD -- claimweb/ data/ tests/ 2>/dev/null | head -1)
    log_changed=$(git diff --name-only HEAD -- CHANGELOG.md 2>/dev/null)
    log_staged=$(git diff --name-only --cached -- CHANGELOG.md 2>/dev/null)
    if [ -n "$code_changed" ] && [ -z "$log_changed$log_staged" ]; then
        reasons+=("Code or data changed in this session but CHANGELOG.md was not updated. Append an entry describing what was done before stopping.")
    fi
fi

# 3. Is the TODO "Now" item still the same as when the session started? If yes, has progress been made?
# (Soft check — we can't actually tell whether progress is "real". Just remind.)
# Skipped for now; the explicit CHANGELOG check above is the primary signal.

# 4. Are there test failures we know about?
# Only check if pytest is installed and tests/ exists.
if command -v pytest >/dev/null 2>&1 && [ -d tests/ ]; then
    # Quick check (timeout 30s) of any tests in test_smoke.py or marked smoke.
    if pytest tests/ -x -q --co -m smoke >/dev/null 2>&1; then
        # There are smoke tests. Run them with a tight timeout.
        if ! timeout 30 pytest tests/ -x -q -m smoke >/tmp/claimweb_smoke 2>&1; then
            smoke=$(tail -20 /tmp/claimweb_smoke)
            reasons+=("Smoke tests failing:\n$smoke\nFix before stopping.")
        fi
    fi
fi

# If no reasons, allow stop.
if [ ${#reasons[@]} -eq 0 ]; then
    rm -f "$counter_file"
    exit 0
fi

# Otherwise, increment counter and block.
echo $((count + 1)) > "$counter_file"

combined=$(printf "%s\n\n" "${reasons[@]}")
jq -n --arg reason "$combined" '{
  "decision": "block",
  "reason": ("Cannot stop yet. The following must be addressed:\n\n" + $reason + "\n\n(This is the Stop hook. If these are genuinely not relevant or the user has explicitly accepted them, you can stop again — after 3 challenges this hook allows stop.)")
}'

exit 0
