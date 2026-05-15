#!/usr/bin/env bash
# Precommit gate for CLAIM-WEB.
# Run this before every git commit. The Stop hook reminds; this script enforces.
#
# Failure modes are categorized:
#   FATAL — must fix before commit (tests fail, conservation laws violated)
#   WARNING — should fix but doesn't block commit (lint, todo bloat)
#
# Usage:
#   bash scripts/precommit_gate.sh
#   bash scripts/precommit_gate.sh --strict    # treat warnings as fatal
#
# Exit codes:
#   0 — gate passed
#   1 — fatal failures
#   2 — warnings only (or fatal under --strict)

set -uo pipefail  # not -e; we want to continue and report all failures.

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR"

STRICT=0
[ "${1:-}" = "--strict" ] && STRICT=1

fatal=0
warning=0

red() { printf "\033[31m%s\033[0m\n" "$1"; }
green() { printf "\033[32m%s\033[0m\n" "$1"; }
yellow() { printf "\033[33m%s\033[0m\n" "$1"; }

section() { printf "\n=== %s ===\n" "$1"; }

# 1. pytest, fast tests first.
# Prefer uv run (project venv) → .venv/bin/pytest → system pytest.
section "pytest (unit + smoke)"
if [ -d tests/ ]; then
    if command -v uv >/dev/null 2>&1; then
        PYTEST_CMD="uv run pytest"
    elif [ -x ".venv/bin/pytest" ]; then
        PYTEST_CMD=".venv/bin/pytest"
    elif command -v pytest >/dev/null 2>&1; then
        PYTEST_CMD="pytest"
    else
        PYTEST_CMD=""
    fi

    if [ -n "$PYTEST_CMD" ]; then
        if $PYTEST_CMD tests/ -x -q --ignore=tests/validation -m "not integration" 2>&1 | tail -40; then
            green "pytest unit/smoke: PASS"
        else
            red "pytest unit/smoke: FAIL — fatal"
            fatal=$((fatal + 1))
        fi
    else
        yellow "pytest not available — skipping (warning)"
        warning=$((warning + 1))
    fi
else
    yellow "no tests/ directory — skipping (warning)"
    warning=$((warning + 1))
fi

# 2. Conservation-law checker on any solved networks present.
section "conservation laws"
if [ -f scripts/check_conservation.py ] && command -v python >/dev/null 2>&1; then
    if python scripts/check_conservation.py 2>&1 | tail -20; then
        green "conservation laws: PASS"
    else
        red "conservation laws: FAIL — fatal"
        fatal=$((fatal + 1))
    fi
else
    yellow "conservation checker not present — skipping (warning)"
    warning=$((warning + 1))
fi

# 3. No paid-aggregator references in source.
section "no paid aggregator"
if [ -x scripts/check_data_sources.sh ]; then
    if bash scripts/check_data_sources.sh 2>&1; then
        green "data sources: PASS"
    else
        red "data sources: FAIL — fatal"
        fatal=$((fatal + 1))
    fi
else
    yellow "data-source checker not present — skipping (warning)"
    warning=$((warning + 1))
fi

# 4. Lint.
section "ruff"
if command -v ruff >/dev/null 2>&1; then
    if ruff check claimweb/ 2>&1; then
        green "ruff: PASS"
    else
        yellow "ruff: issues found — warning"
        warning=$((warning + 1))
    fi
else
    yellow "ruff not installed — skipping (warning)"
    warning=$((warning + 1))
fi

# 5. CHANGELOG and TODO are not stale.
section "log/todo freshness"
if [ -f CHANGELOG.md ] && [ -f TODO.md ]; then
    if [ -d .git ]; then
        # If anything under claimweb/ or data/ changed in the staged commit but CHANGELOG.md is not staged or modified, flag.
        staged_code=$(git diff --cached --name-only -- claimweb/ data/ tests/ 2>/dev/null | head -1)
        staged_log=$(git diff --cached --name-only -- CHANGELOG.md 2>/dev/null)
        mod_log=$(git diff --name-only -- CHANGELOG.md 2>/dev/null)
        if [ -n "$staged_code" ] && [ -z "$staged_log$mod_log" ]; then
            yellow "CHANGELOG.md not updated despite code/data changes — warning"
            warning=$((warning + 1))
        else
            green "log/todo freshness: PASS"
        fi
    fi
fi

# 6. Conservation laws on solved-network outputs (if any).
section "data integrity"
if [ -d data/output ]; then
    bad=$(find data/output -name "*.parquet" -newer .claude/.last_gate_run 2>/dev/null | head -1)
    if [ -n "$bad" ]; then
        # Just a notice; the actual integrity check is in check_conservation.py above.
        echo "Recently-modified network outputs detected. Conservation check above is authoritative."
    fi
    touch .claude/.last_gate_run 2>/dev/null || true
fi

section "summary"
echo "Fatal failures:   $fatal"
echo "Warnings:         $warning"

if [ "$fatal" -gt 0 ]; then
    red "GATE FAILED — fix fatal issues before committing."
    exit 1
fi

if [ "$warning" -gt 0 ] && [ "$STRICT" -eq 1 ]; then
    red "GATE FAILED (strict mode) — warnings treated as fatal."
    exit 1
fi

if [ "$warning" -gt 0 ]; then
    yellow "GATE PASSED with warnings."
    exit 2
fi

green "GATE PASSED."
exit 0
