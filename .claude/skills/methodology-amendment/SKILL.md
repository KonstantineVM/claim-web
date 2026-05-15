---
name: methodology-amendment
description: Process a substantive methodology amendment per project plan §48 governance. Use when changing a cascade rule, runnability classification, recovery rate, fire-sale parameter, constraint formulation, or any other element of the published methodology. Triggers on phrases like "amend the methodology", "change the cascade rule", "update the parameter", "methodology amendment", "Amendment A1/A2", "re-parameterize". Encodes the governance process that keeps the methodology auditable.
---

# Methodology amendment governance

After the methodology paper is published, the methodology is *frozen* in the form that was peer-reviewed (project plan §48). Subsequent changes go through a numbered amendment process. This is not bureaucracy — it is what allows external researchers, regulators, and replicators to reason about which version of the methodology produced which dataset.

Even *before* publication, the same discipline applies in milder form: methodology decisions are documented, dated, and justified.

## The two change types

### Amendment (A1, A2, ...)

A *substantive* methodology change. Examples:
- Adding a new arc class (e.g., synthetic CDO if it becomes empirically relevant)
- Changing a cascade rule (e.g., switching from proportional payment to seniority-respecting)
- Changing a recovery rate parameter outside the published range
- Adding or removing a binding regulatory constraint
- Changing the runnability classification of an instrument

Each amendment is documented in `docs/methodology_amendments.md` with:
- Amendment number (A1, A2, ...)
- Date proposed
- Date applied
- Author
- Rationale (1–2 paragraphs)
- Before-and-after comparison (the algorithmic or parameter change in formal terms)
- Impact on all three historical retrodictions (re-run; report new pass/fail)
- Any downstream document changes (data dictionary, methodology paper, technical handbook)

### Patch (P1, P2, ...)

A *non-substantive* fix. Examples:
- Bug fix that changes a result by less than tolerance
- Typo, naming consistency, refactoring without behavior change
- Performance optimization that produces identical output

Patches go in `docs/methodology_patches.md` with date and short description.

## The amendment workflow

When invoked, this skill runs the following workflow:

### Step 1 — Justify

Read the user's stated rationale. Verify it makes sense against the project plan. If the rationale boils down to "to make the validation pass," that is *overfitting* (per project plan §32, "no parameter-tuning to fit" discipline). Surface this concern; do not silently proceed.

Acceptable rationales:
- New published research updates a parameter estimate within the published range
- A peer reviewer or external expert identified a methodological gap
- The data sources have changed and require schema accommodation
- A bug was identified in the prior methodology

### Step 2 — Branch

Methodology amendments are big enough that they go on their own git branch: `experiment/amendment-AN-<short-name>`. The main branch stays at the prior methodology until the amendment is validated.

### Step 3 — Apply

The actual code change. Follow the relevant authoring skill (constraint-author, reconstruction-author, cascade-author, etc.) for the area being amended.

### Step 4 — Re-run validation

This is the critical step. The amendment is re-run against all three historical episodes:

```bash
pytest tests/validation/ -v
```

Outcomes:
- **All three pass**: amendment is viable. Proceed to step 5.
- **One or more fails**: amendment broke validation. Surface to user with diagnostic; do not merge to main.
- **Tolerance just barely passed**: surface to user; the amendment may be brittle.

If any prior-passing validation now fails, that is a regression. The amendment cannot proceed without resolution.

### Step 5 — Document

Update `docs/methodology_amendments.md` with the full entry. Spawn `documentation-curator` subagent to propagate the change to:
- `docs/METHODOLOGY.md` (the formal spec)
- `docs/data_dictionary/` (if the amendment touches data taxonomy)
- The methodology paper draft (`docs/paper/`)
- The technical handbook (`docs/technical_handbook/`)
- The data dictionary (`docs/data_dictionary/`)
- Any downstream documents

### Step 6 — Re-version the dataset

The published dataset is versioned. After an amendment:
- Bump the methodology version in `claimweb/__init__.py`'s `__methodology_version__` constant
- Re-run the full panel reconstruction (or, if too expensive, schedule it and flag the dataset version)
- Old dataset versions remain accessible (not silently overwritten)
- New solved networks go to `data/output/network/{period}/vN/` where N is the new version

### Step 7 — User confirmation

The amendment is *not* merged to main until the user explicitly confirms. Present:
- The amendment rationale
- The validation results
- The impact on the dataset
- The downstream document changes
- A summary diff

Wait for "yes, merge it" before merging to main. No exceptions.

### Step 8 — Merge and tag

When confirmed:
1. Merge the branch to main (fast-forward if possible, otherwise a merge commit with the amendment summary in the message)
2. Tag the merge commit `methodology-AN`
3. Update `CHANGELOG.md` with a top-level entry
4. Push tags

## What constitutes a published methodology

Before peer-review publication, the "published" methodology is whatever is on main at the most recent phase-gate closure. After peer-review publication, the published methodology is the version that was peer-reviewed (tagged `methodology-published-v1`). Both are immutable; subsequent change requires this amendment process.

## What not to do

- Do not amend the methodology to pass a validation that is failing. Re-parameterization within published ranges is acceptable; structural changes to fit validation are overfitting.
- Do not bundle multiple unrelated amendments into one. Each amendment is one change with its own rationale.
- Do not skip the validation re-run. The validation is what makes the amendment a non-regression.
- Do not delete prior amendment entries. They are the project's institutional memory.
- Do not amend on `main` directly. Use a branch.
- Do not promote an amendment to "merged" without user confirmation. Even if you are very sure.

## The relationship to project plan §52

Project plan §52 specifies that scope and methodology decisions are user-authorized. This skill operationalizes that: it does the *work* of an amendment (branch, apply, validate, document) but stops short of *merging* until the user confirms. The user retains decision authority; the skill provides the rigor.
