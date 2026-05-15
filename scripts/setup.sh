#!/usr/bin/env bash
# Setup script for the CLAIM-WEB harness.
# Run once after cloning. Verifies prerequisites and makes scripts executable.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "CLAIM-WEB harness setup"
echo "  Project dir: $PROJECT_DIR"
echo ""

# 1. Make hook scripts executable.
echo "[1/5] Making scripts executable..."
chmod +x scripts/*.sh 2>/dev/null || true

# 2. Check for required CLI tools.
echo "[2/5] Checking required CLI tools..."
missing=()
for tool in jq git python; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        missing+=("$tool")
    fi
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "  MISSING: ${missing[*]}"
    echo "  Install these before running Claude Code in this directory."
    exit 1
fi
echo "  jq, git, python: OK"

# 3. Check for recommended Python tools.
echo "[3/5] Checking recommended Python tools..."
for tool in pytest ruff hypothesis; do
    if python -c "import $tool" 2>/dev/null; then
        echo "  python -m $tool: OK"
    else
        echo "  python -m $tool: MISSING (install via 'pip install $tool' — recommended)"
    fi
done

# 4. Initialize state files if missing.
echo "[4/5] Initializing state files..."
for f in CHANGELOG.md TODO.md; do
    if [ ! -f "$f" ]; then
        echo "  $f missing — the harness template should have provided it. Verify."
    else
        echo "  $f: OK"
    fi
done

if [ ! -f CLAUDE.md ]; then
    echo "  CLAUDE.md missing — fatal."
    exit 1
else
    echo "  CLAUDE.md: OK"
fi

# 5. Sanity-check hooks settings.
echo "[5/5] Verifying .claude/settings.json..."
if [ -f .claude/settings.json ]; then
    if jq empty .claude/settings.json >/dev/null 2>&1; then
        echo "  .claude/settings.json: OK (valid JSON)"
    else
        echo "  .claude/settings.json: INVALID JSON — fatal."
        exit 1
    fi
else
    echo "  .claude/settings.json missing — fatal."
    exit 1
fi

echo ""
echo "Setup complete."
echo ""
echo "Next steps:"
echo "  1. Start Claude Code in this directory."
echo "  2. In your first session, run /claimweb-bootstrap to scaffold the Python package."
echo "  3. Then /claimweb-status to see the current state."
echo ""
