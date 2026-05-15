#!/usr/bin/env bash
# PostToolUse hook for Write/Edit/MultiEdit. Runs fast checks after every file edit.
# These checks are FAST (<500ms) to keep sessions responsive.
# Slow checks (full pytest, full conservation across all networks) belong in pre-commit, not here.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR"

# Read tool input.
input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')

# If file doesn't exist (deleted), skip.
[ -f "$file_path" ] || exit 0

# Per-file-type checks.
case "$file_path" in
    *.py)
        # Quick syntax check via python -m py_compile. <100ms typically.
        if command -v python >/dev/null 2>&1; then
            if ! python -m py_compile "$file_path" 2>/tmp/claimweb_pycompile_err; then
                err=$(cat /tmp/claimweb_pycompile_err)
                jq -n --arg err "$err" --arg path "$file_path" '{
                  "decision": "block",
                  "reason": ("Python syntax error in " + $path + ":\n" + $err + "\n\nFix syntax before continuing.")
                }'
                exit 0
            fi
        fi

        # If the file is under claimweb/, also run ruff if available.
        case "$file_path" in
            *claimweb/*)
                if command -v ruff >/dev/null 2>&1; then
                    # Auto-fix what can be auto-fixed; report what can't.
                    ruff check --fix "$file_path" 2>/tmp/claimweb_ruff_err || true
                    if [ -s /tmp/claimweb_ruff_err ]; then
                        # Non-blocking notice — let Claude see it but not block.
                        echo "ruff notes (non-blocking) for $file_path:" >&2
                        cat /tmp/claimweb_ruff_err >&2
                    fi
                fi
                ;;
        esac
        ;;

    *.json)
        # Validate JSON.
        if ! jq empty "$file_path" 2>/tmp/claimweb_json_err; then
            err=$(cat /tmp/claimweb_json_err)
            jq -n --arg err "$err" --arg path "$file_path" '{
              "decision": "block",
              "reason": ("Invalid JSON in " + $path + ":\n" + $err + "\n\nFix the JSON before continuing.")
            }'
            exit 0
        fi
        ;;

    *CHANGELOG.md|*TODO.md)
        # No syntax check; markdown is loose. Just a courtesy reminder.
        echo "Reminder: CHANGELOG/TODO updated. If this corresponds to a unit of work completed, commit and push." >&2
        ;;
esac

# Bonus: if the edit touched a file under claimweb/fetchers/, run the no-paid-aggregator post-check
# (the PreToolUse hook already ran but new content might have slipped through if it was added line-by-line).
case "$file_path" in
    */fetchers/*|*claimweb/fetchers/*)
        if grep -qiE 'capitaliq|creditview|moodys.*api|leveragedcommentary' "$file_path"; then
            jq -n --arg path "$file_path" '{
              "decision": "block",
              "reason": ("Paid-aggregator reference detected in fetcher " + $path + ". Remove and use the origin source. See CLAUDE.md.")
            }'
            exit 0
        fi
        ;;
esac

exit 0
