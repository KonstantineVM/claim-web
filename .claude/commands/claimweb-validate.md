---
description: Run the historical validation suite — retrodiction of 2007 XFABS, 2008 AIG sec-lending, 2020 prime MMF/repo stress. Use after major methodology changes or before any deployment claim.
argument-hint: [episode-number]
---

# /claimweb-validate

Run the historical validation suite per project plan §17.

## Arguments

Optional argument selects a specific episode:
- `1` — 2007 XFABS run
- `2` — 2008 AIG securities-lending collapse
- `3` — March 2020 prime MMF / repo stress
- (no argument) — all three

## What to do

1. **Verify prerequisites.** The validation tests live in `tests/validation/`. If they don't exist yet (project is still in Phase 2 or earlier), report that and stop.

2. **Verify the solved networks for the relevant pre-shock periods exist.** Episode 1 needs 2007-Q2 state; Episode 2 needs 2008-Q2 state; Episode 3 needs 2020-Q1 state. If any of these are missing, report that and stop. (The validation cannot proceed without the network state to apply the shock to.)

3. **Run the selected episode(s).** Use the existing test infrastructure:
   ```
   pytest tests/validation/ep1_2007_xfabs.py -v       # Episode 1
   pytest tests/validation/ep2_2008_aig_seclending.py -v   # Episode 2
   pytest tests/validation/ep3_2020_covid_stress.py -v     # Episode 3
   ```
   Capture full output; do not summarize away the diagnostic detail.

4. **Compare retrodiction against the targets:**
   - **Episode 1 target:** approximately $18B loss concentrated at Hartford, ING USA, MetLife, Prudential, AIG SunAmerica. Tolerance ±30%.
   - **Episode 2 target:** approximately $20–25B loss at AIG's life insurance subsidiaries. Tolerance ±30%.
   - **Episode 3 target:** qualitative pattern of FHLB advance surge, stable value stress, no insurer default; FHLB advance increase within ±20%.

5. **Produce a validation report** under `docs/validation/{date}_episode_{N}.md`:
   - Methodology version (read from CHANGELOG)
   - Pre-shock network state used
   - Shock specification applied
   - Cascade output
   - Comparison against historical target
   - Pass/fail per the tolerance bands
   - If fail: hypotheses for the discrepancy

6. **Update CHANGELOG.md** with the validation result. If any episode failed, also update TODO.md to add a "Now" item for re-parameterization investigation.

7. **Do NOT modify model parameters** to make the validation pass within this command. Re-parameterization is a separate workflow that requires user-level discussion of the change.

## What not to do

- Do not silently re-parameterize the model. If the model fails validation, that is *information* — it means a cascade rule, runnability classification, or fire-sale parameter is wrong somewhere. Report the failure; don't paper over it.
- Do not declare validation "passed" if any retrodiction exceeds tolerance. The deployment gate is conjunctive: all three must pass.

## Escalation

If a validation that previously passed begins failing, that is high-priority. Stop, surface to the user, and identify what changed (recent commits, parameter updates, methodology amendment).
