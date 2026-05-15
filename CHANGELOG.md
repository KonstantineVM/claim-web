# CHANGELOG — CLAIM-WEB

Lab-notebook style. Append entries; don't rewrite history. Both successes and failed approaches go here. The "Failed approaches" section is as important as the "Completed" section — without it, successive sessions re-attempt the same dead ends.

## Convention

Each entry begins with a date and short title. Use these section markers within an entry:
- **What:** what was done
- **Why:** why it was done now (which phase / gate)
- **Result:** what came out (with file paths to artifacts)
- **Failed:** what was tried and didn't work, with brief diagnosis
- **Next:** what this unlocks or what comes next

After each meaningful unit of work, append an entry, commit, and push.

## Current status

- **Phase:** Foundation (Phase 1 of 5 per project plan §35)
- **Reference period:** target 2024-Q4 for end-to-end reconstruction
- **First arc target:** FHLB advances → U.S. life insurer members (per project plan first-week actions)
- **Methodology version:** v0 (pre-publication, freely revisable)

## Entries

<!-- Append entries here. Newest first. Example below — delete after first real entry. -->

### 2026-05-15 — Bootstrap: package skeleton

- **What:** Scaffolded the `claimweb/` Python package per project plan §18.
  Created `pyproject.toml` with all §19 dependencies (pinned floors with
  reasonable ceilings); created every package and module per §18 layout
  with module-level docstrings cross-referencing the relevant plan sections;
  created `tests/` (unit / integration / validation tiers per §21) with
  a single bootstrap smoke test that imports every subpackage and module
  and verifies each has a docstring; created `data/raw/`,
  `data/normalized/`, `data/output/`, and `notebooks/` placeholders;
  updated `.gitignore` to (a) preserve the `data/raw/.gitkeep` and (b)
  ignore future `data/output/network/*/v*/` directories.
- **Why:** Phase 1 gate criterion: `claimweb/` Python package skeleton
  exists with module-level docstrings referencing project-plan sections,
  and `pyproject.toml` exists with pinned dependencies (per
  `/claimweb-bootstrap` and `docs/PHASE_GATES.md`).
- **Result:** 73 unit tests pass; ruff clean; precommit gate green.
  Every module compiles (`python -m py_compile`) and every subpackage
  imports cleanly. Package installs with `pip install -e ".[dev]"` against
  the locked-in dependency set.
- **Failed:** The precommit gate's `scripts/check_data_sources.sh` was
  matching its own pattern strings inside `scripts/` (false positives on
  `guard_no_paid_aggregator.sh`, `guard_bash.sh`, `post_edit_check.sh`,
  and itself). The enforcement scripts have to contain the pattern strings
  in order to detect them; the grep was just too aggressive. Fixed by
  adding `--exclude` filters for the four enforcement scripts. This is
  a harness bug that would have blocked every subsequent commit until
  resolved.
- **Next:** First fetcher — `claimweb.fetchers.base` (the `BaseFetcher`
  abstraction and `ArcFact` schema) per the `fetcher-author` skill.
  Once that lands, `claimweb.fetchers.fhlb_combined` follows.

---

## Standing reminders

When updating this file:
- Don't delete old entries even when retired — they're the project's institutional memory.
- Cross-reference project-plan section numbers when relevant.
- If you tried an approach that failed, describe *why* it failed — not just that it did. Future sessions read this and will repeat the failure without that context.
- When a phase gate is hit (see `docs/PHASE_GATES.md`), add a phase-gate entry summarizing the gate criteria and how they were met.

