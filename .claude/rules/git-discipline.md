---
description: Git discipline — commits, branches, push cadence, and what never to commit. Applies to every session.
---

# Git discipline

CLAIM-WEB uses git as the coordination layer (per Mishra-Sharma 2026 Anthropic post). The discipline below is enforced partially by hooks (`scripts/guard_bash.sh` blocks force-push and hard-reset, `scripts/stop_review.sh` blocks Stop if uncommitted changes are in important paths) and partially by convention.

## Commit cadence

- **Commit after every meaningful unit of work.** A unit of work is: one fetcher implemented + tested, one constraint module implemented + tested, one bug fixed + test added, one phase-gate criterion closed. Not every file save.
- **Run `scripts/precommit_gate.sh` before commit.** The Stop hook reminds; the gate script enforces.
- **Push after every commit.** Local commits without pushes are vulnerable to laptop loss, compute-allocation timeout, or session crash. Push immediately.
- **One commit, one logical change.** Mixing a fetcher implementation and a methodology amendment in one commit makes review impossible.

## Commit message format

```
<area>: <imperative summary>

<body explaining what and why, referencing project plan section>
<one blank line>
<co-authors if applicable>
```

Areas: `fetcher`, `constraints`, `reconstruct`, `cascade`, `validation`, `visualize`, `abm`, `docs`, `infra`, `phase`.

Examples:
```
fetcher: FHLB Combined Financial Report v1

Implements claimweb.fetchers.fhlb_combined per project plan §10.4.
Acquires quarterly PDF, extracts top-line tables, emits A3 arcs.
Unit test on captured 2024-Q4 fixture.

(closes TODO item "[fetcher] FHLB Combined")
```

```
constraints: balance-sheet identity (Law 1) with property tests

Implements claimweb.constraints.kcl with hypothesis-based property
tests verifying soundness, completeness, stability, and independence
per constraint-author skill.
```

```
phase: close Phase 1 (2026-08-15)

All Phase 1 gate criteria verified per docs/PHASE_GATES.md.
Reference 2024-Q4 reconstruction passes conservation checker.
Promoting Phase 2 TODO items.
```

## What never to commit

Hooks block what they can. The list below is enforced as a soft commitment:

- **Raw downloaded data files.** `data/raw/` is gitignored; data is content-addressed and archived separately (per project plan §47).
- **Solved networks with `UNRESOLVED` quality flags.** Solved outputs go to `data/output/`; an output containing unresolved flags is incomplete and shouldn't be committed.
- **Credentials, API keys, tokens.** None should exist in this project (all data sources are free, public). If you find yourself writing a credential, stop and surface — the credential probably belongs in an environment variable, not in code.
- **Notebook outputs.** `notebooks/` should be committed with cleared outputs.
- **Session log artifacts.** `.claude/session-log/` is gitignored (large, low value).
- **Compiled Python.** `__pycache__/`, `*.pyc`, `*.pyo`.
- **OS junk.** `.DS_Store`, `Thumbs.db`, `desktop.ini`.

## Branching

- **`main` is the deployment branch.** All commits go through `main` for v1.
- **Long experiments live on branches.** A methodology amendment that may not pan out goes on a branch named `experiment/<short-name>`. If it pans out, merge to main via fast-forward; if not, abandon (don't delete — keeps the record).
- **No PRs against `main` from forks during the v1 build.** External contributors come post-publication.

## Destructive operations

The bash guard hook (`scripts/guard_bash.sh`) blocks:
- `git push --force` and `git push -f` — could overwrite shared history
- `git reset --hard HEAD~N` — could lose work

If you legitimately need either, surface to the user; they can run it manually. The block is intentional friction.

## When commits go wrong

If a commit is bad (broke tests, introduced a paid-aggregator reference somehow, etc.):
1. **Don't rewrite history on `main`.** Revert with `git revert <hash>` instead.
2. **Append a CHANGELOG entry** documenting the revert and what was wrong.
3. **If a Push went out before the revert**, force-push is *still* blocked. The revert is on top of the bad commit; the history is preserved.

## Co-authoring

Claude-authored commits include:
```
Co-Authored-By: Claude <claude@anthropic.com>
```
on the last line of the commit body, per Anthropic's recommended convention for AI-assisted work.

## Tags for milestones

Phase-gate closures get a tag:
```
git tag -a phase-1-close -m "Phase 1 closed YYYY-MM-DD"
git push --tags
```

Manuscript submissions, web product launches, and Zenodo deposits also get tags. Tags don't move; they document the artifact state at that moment.
