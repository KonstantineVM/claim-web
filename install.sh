#!/usr/bin/env bash
# CLAIM-WEB harness installer.
# Copies this harness into a target project root, preserving existing files where conflicts would occur.
#
# Usage:
#   bash install.sh /path/to/project-root
#   bash install.sh /path/to/project-root --force   (overwrite conflicting files)
#   bash install.sh /path/to/project-root --dry-run (show what would happen)

set -euo pipefail

# Locate this harness directory (where install.sh lives).
HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse args.
TARGET=""
FORCE=0
DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        --dry-run) DRY_RUN=1 ;;
        -h|--help)
            cat <<EOF
CLAIM-WEB harness installer

Usage: bash install.sh <target-dir> [--force] [--dry-run]

  <target-dir>   Project root where the harness should be installed
  --force        Overwrite existing files (dangerous; CHANGELOG/TODO content will be lost)
  --dry-run      Show what would be copied without writing anything

Files copied:
  - CLAUDE.md                  (project memory; never overwritten without --force)
  - CHANGELOG.md               (progress log; never overwritten without --force)
  - TODO.md                    (task list; never overwritten without --force)
  - README.md                  (harness README; renamed to HARNESS_README.md if README.md exists)
  - .claude/                   (settings, skills, agents, commands, hooks, rules; merged)
  - scripts/                   (hook scripts and gates; merged)
  - docs/PHASE_GATES.md        (gate criteria; never overwritten without --force)

After installation:
  1. cd <target-dir>
  2. Place docs/CLAIM_WEB_PROJECT_PLAN.md and docs/REGULATORY_ARBITRAGE.md from the
     project root into the new docs/ directory. (The installer does not include them;
     they are project artifacts, not harness artifacts.)
  3. bash scripts/setup.sh
  4. Start Claude Code in <target-dir>
  5. In your first session, run /claimweb-bootstrap
EOF
            exit 0
            ;;
        -*)
            echo "Unknown option: $arg" >&2
            exit 1
            ;;
        *)
            if [ -z "$TARGET" ]; then
                TARGET="$arg"
            else
                echo "Multiple targets specified; use only one" >&2
                exit 1
            fi
            ;;
    esac
done

if [ -z "$TARGET" ]; then
    echo "Usage: bash install.sh <target-dir> [--force] [--dry-run]" >&2
    echo "Run 'bash install.sh --help' for full usage." >&2
    exit 1
fi

# Resolve target to absolute path.
mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"

if [ "$TARGET" = "$HARNESS_DIR" ]; then
    echo "ERROR: target is the harness source itself. Pick a different directory." >&2
    exit 1
fi

echo "CLAIM-WEB harness installer"
echo "  Harness source: $HARNESS_DIR"
echo "  Target root:    $TARGET"
[ "$DRY_RUN" -eq 1 ] && echo "  Mode:           DRY RUN (no files will be written)"
[ "$FORCE" -eq 1 ] && echo "  Mode:           FORCE (existing files will be overwritten)"
echo ""

# Counter for reporting.
copied=0
skipped=0
forced=0
renamed=0

# Function: copy a single file with conflict handling.
copy_file() {
    local src="$1"
    local rel="$2"
    local dst="$TARGET/$rel"
    local dst_dir
    dst_dir="$(dirname "$dst")"

    if [ -e "$dst" ]; then
        if [ "$FORCE" -eq 1 ]; then
            if [ "$DRY_RUN" -eq 1 ]; then
                echo "  FORCE  $rel  (would overwrite existing)"
            else
                cp "$src" "$dst"
                echo "  FORCE  $rel"
            fi
            forced=$((forced + 1))
        elif [ "$rel" = "README.md" ]; then
            # Special case: existing README → write as HARNESS_README.md
            local renamed_dst="$TARGET/HARNESS_README.md"
            if [ -e "$renamed_dst" ] && [ "$FORCE" -eq 0 ]; then
                echo "  SKIP   $rel  (HARNESS_README.md also exists)"
                skipped=$((skipped + 1))
            else
                if [ "$DRY_RUN" -eq 1 ]; then
                    echo "  RENAME $rel → HARNESS_README.md"
                else
                    cp "$src" "$renamed_dst"
                    echo "  RENAME $rel → HARNESS_README.md"
                fi
                renamed=$((renamed + 1))
            fi
        else
            echo "  SKIP   $rel  (already exists; use --force to overwrite)"
            skipped=$((skipped + 1))
        fi
    else
        if [ "$DRY_RUN" -eq 1 ]; then
            echo "  COPY   $rel"
        else
            mkdir -p "$dst_dir"
            cp "$src" "$dst"
            echo "  COPY   $rel"
        fi
        copied=$((copied + 1))
    fi
}

# Walk the harness directory and copy each file.
cd "$HARNESS_DIR"
while IFS= read -r -d '' src; do
    rel="${src#./}"
    # Skip the installer itself.
    [ "$rel" = "install.sh" ] && continue
    copy_file "$src" "$rel"
done < <(find . -type f -not -path './.git/*' -not -path '*/__pycache__/*' -not -name '*.pyc' -print0 | sort -z)

# Set scripts executable.
if [ "$DRY_RUN" -eq 0 ]; then
    chmod +x "$TARGET"/scripts/*.sh 2>/dev/null || true
fi

# Summary.
echo ""
echo "Summary:"
echo "  Copied:   $copied"
echo "  Renamed:  $renamed"
echo "  Forced:   $forced"
echo "  Skipped:  $skipped"

if [ "$DRY_RUN" -eq 1 ]; then
    echo ""
    echo "Dry run complete. No files were written."
    exit 0
fi

# Post-install verification.
echo ""
echo "Verifying installation..."
cd "$TARGET"

missing=()
for required in CLAUDE.md CHANGELOG.md TODO.md .claude/settings.json scripts/setup.sh; do
    if [ ! -e "$required" ]; then
        missing+=("$required")
    fi
done

if [ ${#missing[@]} -gt 0 ]; then
    echo "WARNING: installation incomplete. Missing files:"
    printf "  %s\n" "${missing[@]}"
    exit 1
fi

if command -v jq >/dev/null 2>&1; then
    if ! jq empty .claude/settings.json >/dev/null 2>&1; then
        echo "WARNING: .claude/settings.json is not valid JSON"
        exit 1
    fi
elif command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
    py="$(command -v python3 || command -v python)"
    if ! "$py" -c "import json,sys; json.load(open('.claude/settings.json'))" >/dev/null 2>&1; then
        echo "WARNING: .claude/settings.json is not valid JSON"
        exit 1
    fi
else
    echo "NOTE: neither jq nor python found; skipping JSON validation. Install jq before starting Claude Code."
fi

echo "Installation verified."
echo ""
cat <<EOF
Next steps:

  1. Place the project documents (CLAIM_WEB_PROJECT_PLAN.md, REGULATORY_ARBITRAGE.md)
     into $TARGET/docs/. The installer does not include them.

  2. Run setup to make hooks executable and check prerequisites:
       cd $TARGET
       bash scripts/setup.sh

  3. Start Claude Code in $TARGET.

  4. In your first session, run:
       /claimweb-bootstrap

  5. Read CLAUDE.md and the project plan before substantive work begins.
EOF
