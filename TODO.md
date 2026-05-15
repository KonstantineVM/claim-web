# TODO — CLAIM-WEB

Current-state task list. Read this at the start of every session.

## How this file works in autonomous mode

The top of the file is "Now" — the single next thing to work on. Each session:

1. Completes the current Now item.
2. Moves the completed item to "Done" with the commit hash.
3. Promotes the top "Next" item to "Now".
4. Promotes a Backlog item to fill the Next slot.

Claude does this without asking. The next session picks up the new Now.

---

## Now

- **[fetcher]** Implement `claimweb.fetchers.frb_efa_fabs`: FRB Enhanced Financial Accounts FABS daily dataset, per project plan §10.9. Provides intra-quarter FABN funding-agreement issuance flow data. Per `fetcher-author` skill.

## Next

1. **[fetcher]** `claimweb.fetchers.sec_nmfp`: SEC Form NMFP MMF holdings (per project plan §10.5)
2. **[fetcher]** `claimweb.fetchers.sec_adv`: SEC Form ADV investment adviser registrations (per project plan §10.6)
3. **[fetcher]** `claimweb.fetchers.naic_schedule_s`: NAIC Schedule S reinsurance (per project plan §10.3) — spawn `data-source-investigator` first
4. **[fetcher]** `claimweb.fetchers.naic_schedule_d`: NAIC Schedule D security-by-security
5. **[fetcher]** `claimweb.fetchers.sec_13f`: SEC Form 13F institutional holdings (per project plan §10.7)
6. **[reconstruction]** `claimweb.reconstruct.max_entropy`: per project plan §13 Phase C; before writing code, spawn `literature-checker` against Upper (2004)
7. **[infra]** Reference quarter 2024-Q4 acquired end-to-end with all Phase 1 fetchers
## Backlog

### Phase 1 — Foundation (months 1–6)

Per project plan §35 and `docs/PHASE_GATES.md`.

- **[fetcher]** `claimweb.fetchers.naic_schedule_d`: NAIC Schedule D security-by-security
- **[reconstruction]** `claimweb.reconstruct.max_entropy`: per project plan §13 Phase C; before writing code, spawn `literature-checker` against Upper (2004)
- **[reconstruction]** `claimweb.reconstruct.min_density`: per project plan §13 Phase C; spawn `literature-checker` against Anand-Craig-von Peter (2015)
- **[fetcher]** `claimweb.fetchers.sec_13f`: SEC Form 13F institutional holdings (per project plan §10.7)
- **[reconstruction]** `claimweb.reconstruct.solver`: the harness that runs both methods and brackets per project plan §13
- **[infra]** Reference quarter 2024-Q4 acquired end-to-end with all Phase 1 fetchers
- **[infra]** 2024-Q4 reconstructed via both methods; output in `data/output/network/2024-Q4/v1/`
- **[infra]** Conservation laws verified on 2024-Q4 reconstruction
- **[visualize]** Initial Sankey visualization for 2024-Q4 — per `visualization-author` skill
- **[docs]** Phase 1 sections of methodology paper drafted in `docs/METHODOLOGY.md`
- **[phase-gate]** Close Phase 1 — use `phase-gate-closer` skill; this is a user-confirmation event

### Phase 2 — Historical reconstruction (months 7–12)

Items in Phase 2 are deferred until Phase 1 is closed. Listed in `docs/PHASE_GATES.md`.

### Phase 3 — Validation (months 13–18)

Listed in `docs/PHASE_GATES.md`.

### Phase 4 — External review (months 19–24)

Listed in `docs/PHASE_GATES.md`.

### Phase 5 — Publication (months 25–30)

Listed in `docs/PHASE_GATES.md`.

## Done

<!-- Move completed items here. Keep ~30 days, prune monthly. -->

- **[constraints]** 2026-05-15 — Implemented `claimweb.constraints.compile`: aggregates all four laws into a single sparse linear system (`CompiledSystem` + `LawStats` + `compile_constraints`). Law 1 always applied; Laws 2/3/4 conditional on inputs; non-negativity opt-in. 57 tests (4 property-based); 538 total pass; gate green. Also fixed `precommit_gate.sh` to use `uv run pytest`. See CHANGELOG 2026-05-15 "constraints: compile". Commit: 7296c21.
- **[constraints]** 2026-05-15 — Implemented `claimweb.constraints.flow_funds`: Law 4 (flow-of-funds transactions-vs-positions identity). `build_flow_funds_rows` emits one `LinearConstraint` per arc in flow_terms spanning two periods (coefficient +1 for period_to arc, −1 for period_from arc); `check_flow_funds` verifies concrete network pairs. 44 tests (5 property-based via hypothesis: soundness, completeness, stability, independence, provenance round-trip); 481 total pass; gate green. See CHANGELOG 2026-05-15 "constraints: flow-of-funds (Law 4)".
- **[constraints]** 2026-05-15 — Implemented `claimweb.constraints.sectoral`: Law 3 (Z.1 sectoral aggregate constraints). `build_sectoral_rows` emits one `LinearConstraint` per (sector, instrument, side) entry; `check_sectoral` verifies concrete networks. 37 tests (5 property-based via hypothesis: soundness, completeness, stability, independence); 437 total pass; gate green. See CHANGELOG 2026-05-15 "constraints: Z.1 sectoral aggregate (Law 3)".
- **[fetcher]** 2026-05-15 — Implemented `claimweb.fetchers.sec_xbrl`: `SecXbrlFetcher` with LIFE_INSURERS panel (15 entities, CIK-mapped), `_TAG_MAP` (9 us-gaap tags → A1/A3/A4/A5/A12 arcs), `_extract_best_fact` (primary-form+frame preference), `list_available_periods`, `acquire`, `parse`, `validate`. Fixture at `tests/fixtures/sec_xbrl/CIK0001099219.json`. 81 tests; 400 total pass; gate green. See CHANGELOG 2026-05-15 "fetcher: SEC XBRL companyfacts".
- **[constraints]** 2026-05-15 — Implemented `claimweb.constraints.double_entry`: Law 2 (double-entry consistency). `build_double_entry_rows` emits one `LinearConstraint` per instrument with a known boundary term; `check_double_entry` verifies concrete networks. 40 tests (5 property-based via hypothesis: soundness, completeness, stability, independence). 319 total pass; gate green. See CHANGELOG 2026-05-15 "constraints: double-entry consistency (Law 2)".
- **[fetcher]** 2026-05-15 — Implemented `claimweb.fetchers.z1`: `Z1Fetcher` with `list_available_periods`, `acquire`, `parse`, `validate`. Downloads all 7 target tables (L.116, L.121, L.207, L.208, L.211, L.226, L.227) from the FRB DDP; parses the CSV format; maps 27 key series to ArcFacts with `DIRECT_MEASURED`/`stock_eop`. 79 new tests including 3 property-based; 279 total pass; precommit gate green. See CHANGELOG 2026-05-15 entry "fetcher: FRB Z.1". Commit: 9b19adf.
- **[constraints]** 2026-05-15 — Implemented `claimweb.constraints.kcl`: Law 1 (balance-sheet identity / KCL) checker. `build_kcl_rows` compiles one sparse linear equality per node; `check_kcl` verifies the identity on a concrete network. 35 tests (5 property-based via hypothesis: soundness, completeness, stability, independence, plus 30 unit tests). 200 total pass; precommit gate green. See CHANGELOG 2026-05-15 entry "constraints: balance-sheet identity Law 1". Commit: 2c64019.
- **[fetcher]** 2026-05-15 — Implemented `claimweb.fetchers.fhlb_combined`: `FhlbCombinedFetcher` with `list_available_periods`, `acquire`, `parse` (A3 aggregate + named-insurer arcs), `validate`. Fixture at `tests/fixtures/fhlb_combined/2024-Q4-combined-financial-report.pdf`. 44 new tests; 165 total pass; precommit gate green. See CHANGELOG 2026-05-15 entry "fetcher: FhlbCombinedFetcher".
- **[fetcher]** 2026-05-15 — Implemented `claimweb.fetchers.base`: `BaseFetcher` ABC, `ArcFact` schema, `Period`, `ArcClass`, `DataQualityFlag`, `RawDataHandle`, `ValidationReport`. 48 new tests (unit + hypothesis property-based); 121 total pass; precommit gate green. See CHANGELOG 2026-05-15 entry "fetcher: BaseFetcher abstraction and ArcFact schema".
- **[bootstrap]** 2026-05-15 — Initialized `claimweb/` Python package skeleton per project plan §18. `pyproject.toml` with §19 dependencies; every module has a docstring referencing its plan section; `tests/` collects and 73 smoke tests pass; precommit gate green. Also fixed a harness self-reference bug in `scripts/check_data_sources.sh` (enforcement scripts were matching their own pattern lists). See CHANGELOG 2026-05-15 entry.

## Blocked

<!-- Items waiting on user decision or external input. Surface to user when an item here is the only remaining Now-eligible work. -->

---

## Conventions

- Tag items with `[bootstrap]`, `[fetcher]`, `[constraints]`, `[reconstruction]`, `[cascade]`, `[validation]`, `[visualization]`, `[abm]`, `[docs]`, `[infra]`, `[phase-gate]`.
- Each item should reference the relevant project-plan section number and the relevant skill.
- When moving an item to "Done", record the commit hash and the CHANGELOG entry that documents it.
- When promoting Next to Now, also promote a Backlog item into the now-empty Next slot.
- The Next queue is 5–9 items deep at all times.
