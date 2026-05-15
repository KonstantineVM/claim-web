# Phase gates — CLAIM-WEB

This file is the authoritative checklist for phase transitions. The harness reads this file (`scripts/session_start_context.sh`, `scripts/precompact_preserve.sh`, and the `phase-gate-closer` skill) so the gate status is visible to every session.

**Convention.** Each gate criterion is a markdown checkbox `- [ ]` (open) or `- [x]` (closed). When a gate closes, replace the checkbox and append `(closed YYYY-MM-DD, commit <hash>)`. Never delete a criterion — it's the project's commitment.

**Authority.** Gate closure is user-authorized. The `phase-gate-closer` skill verifies that criteria are mechanically met but the actual close-out is a user-confirmed action that includes a milestone commit.

---

## Current phase: Phase 1 — Foundation (months 1–6)

Per project plan §35.

### Phase 1 gate criteria

- [ ] `claimweb/` Python package skeleton exists with module-level docstrings referencing project-plan sections (per `/claimweb-bootstrap`)
- [ ] `pyproject.toml` exists with pinned dependencies per project plan §19
- [ ] `tests/` directory exists with `pytest --collect-only` running without error
- [ ] `BaseFetcher` abstraction in `claimweb/fetchers/base.py` implemented and unit-tested
- [ ] `FhlbCombinedFetcher` implemented end-to-end with unit tests on a captured fixture
- [ ] `Z1Fetcher` implemented for tables L.116, L.121, L.207, L.208, L.211, L.226, L.227
- [ ] `SecXbrlFetcher` implemented (or refactored from FSR Dashboard) for the LIFE_INSURERS panel
- [ ] `FrbEfaFabsFetcher` implemented for the daily FABS dataset
- [ ] Reference quarter 2024-Q4 acquired end-to-end: raw data in `data/raw/`, normalized facts in `data/normalized/`
- [ ] All four conservation-law constraint builders (`kcl`, `double_entry`, `sectoral`, `flow_funds`) implemented with property-based hypothesis tests passing
- [ ] `ConstraintSet` compile step implemented; produces a feasible system on 2024-Q4 data
- [ ] Maximum-entropy reconstruction (`claimweb.reconstruct.max_entropy`) implemented, converges on 2024-Q4 reference
- [ ] Minimum-density reconstruction (`claimweb.reconstruct.min_density`) implemented, converges on 2024-Q4 reference
- [ ] `solver.py` harness implemented; produces bracketed `SolvedNetwork` for 2024-Q4
- [ ] Conservation-law checker (`scripts/check_conservation.py`) verifies all four laws hold on the 2024-Q4 solution within published tolerances
- [ ] Initial Sankey visualization for 2024-Q4 published as a static HTML artifact
- [ ] Methodology paper outline drafted in `docs/METHODOLOGY.md` (Phase 1 sections only)

---

## Phase 2 — Historical reconstruction (months 7–12)

- [ ] Fetchers extended to support 2000-Q1 through 2024-Q4 historical periods (schema versioning per fetcher-author skill)
- [ ] All ~100 quarters acquired end-to-end (raw → normalized → solved)
- [ ] `SolvedNetwork` for each quarter committed to `data/output/network/{period}/` with both ME and MD outputs
- [ ] Eisenberg-Noe core (`claimweb.cascade.eisenberg_noe`) implemented and tested against worked examples from the source paper
- [ ] Fire-sale extension (`claimweb.cascade.fire_sale`) implemented per Cont-Schaanning (2017)
- [ ] Multi-constraint extension (`claimweb.cascade.multi_constraint`) implemented per Coen-Lepore-Schaanning (2019)
- [ ] Contingent-payment extension (`claimweb.cascade.contingent`) implemented per Banerjee-Feinstein (2019)
- [ ] DebtRank (`claimweb.cascade.debtrank`) implemented per Battiston et al. (2012)
- [ ] Cascade simulator harness composes all extensions in the project-plan-specified order
- [ ] Baseline cascade scenarios run for each period; outputs in `data/output/cascades/`
- [ ] First retrodiction attempt for 2007 XFABS — report in `docs/validation/`
- [ ] First retrodiction attempt for 2008 AIG sec-lending — report in `docs/validation/`
- [ ] First retrodiction attempt for 2020 COVID stress — report in `docs/validation/`
- [ ] Conservation laws hold across the full panel (run `scripts/check_conservation.py` against all 100 periods)

---

## Phase 3 — Validation and methodology refinement (months 13–18)

- [ ] Episode 1 (2007 XFABS) retrodiction passes tolerance per `tests/validation/tolerances.py`
- [ ] Episode 2 (2008 AIG sec-lending) retrodiction passes tolerance
- [ ] Episode 3 (March 2020 stress) retrodiction passes tolerance
- [ ] ABM layer (`claimweb/abm/`) implemented and validated against trajectory-fit for all three episodes (project plan Part XII)
- [ ] Sankey renderer (`claimweb/visualize/sankey.py`) produces interactive output across all quarters
- [ ] Node-link renderer (`claimweb/visualize/network_link.py`) implemented
- [ ] Cascade-DAG renderer (`claimweb/visualize/cascade_dag.py`) implemented
- [ ] Multiplier time-series renderer (`claimweb/visualize/multiplier_timeseries.py`) implemented
- [ ] Interactive web product MVP deployed (static frontend + cascade API backend per project plan §24)
- [ ] Methodology paper draft complete (~60–80 pages)
- [ ] Technical handbook draft complete (~100 pages)
- [ ] Data dictionary complete (every node, arc, instrument with definition and source)
- [ ] Reproducibility package (Docker container, `make all` target, `verify.py`) functional

---

## Phase 4 — External review (months 19–24)

- [ ] Pre-submission review by external expert #1 completed (review document in `docs/reviews/`)
- [ ] Pre-submission review by external expert #2 completed
- [ ] Pre-submission review by external expert #3 completed
- [ ] All review comments addressed in writing; revised draft circulated to reviewers
- [ ] Industry briefings completed: at least one rating agency, one chief risk officer, one industry research group
- [ ] FRB Financial Stability Division briefing completed
- [ ] OFR research staff briefing completed
- [ ] FIO Treasury briefing completed
- [ ] NAIC Macroprudential (E) Working Group briefing completed
- [ ] FSB Nonbank Financial Intermediation working group briefing completed
- [ ] Methodology paper submitted to first-choice journal (JF / RFS / JFE / Management Science / Quantitative Finance)
- [ ] Policy-portfolio document drafted (~40 pages, regulator audience)
- [ ] Historical-counterfactuals report drafted

---

## Phase 5 — Publication and launch (months 25–30)

- [ ] Peer-review round 1 received; response written
- [ ] Revision submitted
- [ ] Paper accepted (or moved to next venue per priority order)
- [ ] Web product launched at stable domain with 5-year hosting commitment
- [ ] Open-source code released on GitHub under MIT license
- [ ] Dataset deposited on Zenodo with DOI
- [ ] Software Heritage code preservation registered
- [ ] University-partner institutional repository deposit confirmed
- [ ] Press kit prepared (Bloomberg, FT, Risk.net, WSJ, Retirement Income Journal)
- [ ] Initial press launch executed
- [ ] At least one major conference presentation given (NBER Summer Institute, AEA, WFA, AFA, or equivalent)
- [ ] At least one quarterly "State of the Web" note published

---

## Standing rules for gate management

- **Never close a gate by self-attestation.** Verification is required: file exists, test passes, artifact accessible.
- **Gate transitions are user-authorized.** The `phase-gate-closer` skill verifies; the user confirms; only then is the milestone commit made.
- **Gates do not reopen.** Once closed, a phase-gate criterion stays closed. If subsequent work invalidates a closed criterion, that is a *regression* — flag it loudly, do not silently reopen the gate.
- **Project plan §35 is the schedule baseline.** Slippage is acceptable; deliberate scope reduction requires user authorization per project plan §52.
