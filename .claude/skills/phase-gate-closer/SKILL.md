---
name: phase-gate-closer
description: Close a project phase per the project-plan §35 timeline. Use at phase transitions (Phase 1 → 2, etc.) to verify gate criteria have been met and to formally hand off to the next phase. Triggers on phrases like "close phase", "phase gate", "transition to phase 2/3/4/5", "phase 1 complete". Ensures phase transitions don't happen by drift.
---

# Closing a phase gate

The project plan §35 specifies five phases. Each phase has gate criteria — concrete artifacts that must exist before the next phase begins. The gates are documented in `docs/PHASE_GATES.md` (which is part of the harness and should be initialized in the bootstrap).

This skill is invoked when the user (or Claude itself) believes a phase is complete.

## Phase gates

### Phase 1 — Foundation (months 1–6)

Closure criteria:
- [ ] `claimweb/` package skeleton exists with docstrings for every module (project plan §18)
- [ ] All Phase-1 fetchers implemented and tested (FHLB Combined, Z.1, SEC XBRL, FRB EFA FABS at minimum)
- [ ] Reference quarter 2024-Q4 acquired end-to-end (raw data in `data/raw/`, normalized facts in `data/normalized/`)
- [ ] All four conservation-law constraint builders implemented with property-based tests passing
- [ ] Reference quarter 2024-Q4 reconstructed via both ME and MD methods; output in `data/output/network/2024-Q4/`
- [ ] Conservation laws verified to hold on the 2024-Q4 solution
- [ ] Initial Sankey visualization for 2024-Q4 published

### Phase 2 — Historical reconstruction (months 7–12)

Closure criteria:
- [ ] Fetchers extended to support 2000-Q1 through 2024-Q4 historical periods
- [ ] All ~100 quarters solved end-to-end
- [ ] Cascade simulator implemented (Eisenberg-Noe, fire-sale, multi-constraint, contingent, DebtRank all integrated)
- [ ] Baseline cascade scenarios run for each period; outputs in `data/output/cascades/`
- [ ] First retrodiction attempts for all three historical episodes
- [ ] Conservation laws hold across the full panel

### Phase 3 — Validation and methodology refinement (months 13–18)

Closure criteria:
- [ ] All three historical retrodiction episodes pass tolerance (no exceptions)
- [ ] Visualization layer complete (Sankey, node-link, cascade-DAG renderers all working)
- [ ] Interactive web product MVP functional
- [ ] Methodology paper draft complete
- [ ] Technical handbook draft complete
- [ ] Data dictionary complete

### Phase 4 — External review (months 19–24)

Closure criteria:
- [ ] Pre-submission review by at least three external experts completed
- [ ] Review comments addressed in writing; revised draft circulated to reviewers
- [ ] Industry briefings (per project plan §28) completed
- [ ] Regulator briefings (FRB, OFR, FIO, NAIC, FSB) completed
- [ ] Methodology paper submitted to first-choice journal

### Phase 5 — Publication and launch (months 25–30)

Closure criteria:
- [ ] Methodology paper accepted (after peer-review rounds)
- [ ] Web product launched and accessible
- [ ] Open-source code release with MIT license
- [ ] Dataset deposited on Zenodo with DOI
- [ ] Software Heritage code preservation registered
- [ ] Press coverage initiated
- [ ] At least one conference presentation given (NBER Summer Institute, AEA, WFA, AFA, or equivalent)

## What to do when invoked

1. **Read the current PHASE_GATES.md** to identify which phase is being closed and which criteria are currently unchecked.

2. **For each unchecked criterion, verify.** Don't take the user's word for it; check the artifact exists and the test passes. Concrete verifications:
   - "Reference quarter solved" — confirm `data/output/network/2024-Q4/` exists with both ME and MD outputs and the conservation check passes.
   - "Retrodiction passes" — spawn `retrodiction-replayer` subagent to confirm the test currently passes (not "passed last week").
   - "Visualization complete" — confirm the visualization scripts run and produce output without error.

3. **If any criterion is unmet, report and stop.** Do not close a gate that isn't actually met. Be specific about what's missing.

4. **If all criteria are met, update PHASE_GATES.md** to mark them checked and date-stamp the gate closure. Add an entry to CHANGELOG.md describing the transition. Update TODO.md: archive the closed phase's items to "Done"; promote the next phase's items to "Now"/"Next"/"Backlog" sections.

5. **Commit with a phase-transition message:** `phase: close Phase {N} ({date})` — this is a milestone commit that should stand out in the git log.

6. **Surface to the user.** Phase transitions are user-visible events. Even though gate closure is mechanical, the transition deserves explicit notification: "Phase {N} closed on {date}. Next phase {N+1} begins. Updated TODO.md priorities."

## What not to do

- Do not close a gate by checking off criteria you haven't verified. The gate's value is the verification.
- Do not skip the documentation step. Phase transitions are institutional memory.
- Do not bundle two phase closures into one operation. They're discrete events.
- Do not close a gate that the user hasn't confirmed wants to be closed. Phase transitions are user-authorized — present the verification result and wait for "yes, close it" before applying the changes.
