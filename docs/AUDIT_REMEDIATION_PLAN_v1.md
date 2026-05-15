# CLAIM-WEB Audit v1 — Remediation Plan

This is the operator-facing plan for closing every gap identified in `docs/AUDIT_REPORT_v1.md` before Phase 1 gate closure. Stages are ordered so earlier ones unblock later ones. Effort estimates assume a single operator working in a non-sandbox environment with network access to public data sources.

## Executive summary

- **Critical-path bottleneck:** G1.09 (reference 2024-Q4 acquired end-to-end).
- **Hard deadline:** Iowa RIU portal sunsets June 30, 2026 (~6 weeks from audit-start). Stage 3 must complete by then or scope-reduce Schedule S.
- **Total minimum critical-path effort:** ~3 weeks of focused work.
- **Single largest defect:** F1 — project plan §1.1 has two contradictory readings of arc direction; 9 of 10 fetchers picked one reading, kcl.py and test_kcl.py and naic_schedule_s picked the other. Stage 3 reconciles.

## Stage 1 — Documentation Reconciliation

Effort: 1 day. No dependencies. Can begin immediately.

### 1.1 Update PHASE_GATES.md to reflect closed Phase 1 criteria
- **Files:** `docs/PHASE_GATES.md`
- **Action:** For criteria G1.01-G1.08, replace `- [ ]` with `- [x] (closed YYYY-MM-DD, commit <SHA>)` per the convention at the top of the file. Map criteria to PR merge SHAs from `git log`.
- **Verification:** `git diff docs/PHASE_GATES.md` shows 8 checkboxes flipped. CI runs green.

### 1.2 Standardize TODO.md Done section commit hashes
- **Files:** `TODO.md`
- **Action:** Replace branch-side SHAs (e.g. `5c2de41` for sec_13f) with the actual merge-commit SHA on `main` (e.g. `f253980`). 7 hashes affected.
- **Verification:** Each Done hash exists in `git log --oneline main`.

### 1.3 Resolve CLAUDE.md `.claude/hooks/` naming drift
- **Files:** `CLAUDE.md`
- **Action:** Replace `.claude/hooks/` with `scripts/` (where the hook scripts actually live) and note that they are wired via `.claude/settings.json`. Either that or create `.claude/hooks/` as a symlink to `scripts/` — but symlink is fragile. Prefer the doc update.
- **Verification:** `grep ".claude/hooks/" CLAUDE.md` returns empty.

### 1.4 Disambiguate project plan §1.1 arc direction
- **Files:** `docs/CLAIM_WEB_PROJECT_PLAN.md`
- **Action:** Replace the §1.1 sentence "This is the **arc weight** on the directed edge from issuer $j$ to holder $i$ for instrument $k$" with: "This is the **arc weight** on the directed edge from holder $i$ to issuer $j$ for instrument $k$ (i.e., the edge points from claim-holder to claim-issuer). The arc convention is uniform throughout CLAIM-WEB: `source_node_id` is the holder of the claim (asset side); `target_node_id` is the issuer of the claim (liability side)." This adopts Reading A.
- **Verification:** §1.1 unambiguously specifies one convention. Every fetcher's docstring matches it after Stage 3.

### 1.5 Disambiguate project plan §3.2 G3 ownership direction
- **Files:** `docs/CLAIM_WEB_PROJECT_PLAN.md`
- **Action:** Replace the §3.2 ambiguous sentence "Operating entities point to their controlling parent. Apollo → Athene (control)…" with: "Ownership/control arcs point from the controlling parent to the controlled affiliate. Example: Apollo → Athene means Apollo (source) controls Athene (target). This is the inverse of the funding-claim direction (G1) — it tracks corporate governance, not financial claims." This matches `sec_adv.py` code.
- **Verification:** §3.2 is internally consistent.

### 1.6 Update `claimweb/fetchers/fred.py` legacy reference
- **Files:** `docs/CLAIM_WEB_PROJECT_PLAN.md:1188`
- **Action:** Replace `fetchers/fred.py (FSR) → claimweb/fetchers/fred.py` with `... → claimweb/fetchers/z1.py`.
- **Verification:** No mention of `fred.py` in trunk.

## Stage 2 — Subagent Reliability Improvements

Effort: 1-2 days. No external dependencies.

### 2.1 Add documentation-only mode to `data-source-investigator`
- **Files:** `.claude/agents/data-source-investigator.md`
- **Action:** Extend agent description with an explicit "If network access fails, produce a structured report with `LIVE_DATA_VALIDATION_REQUIRED = TRUE` and document the expected URL pattern, format, rate limit, and edge cases from public documentation alone."
- **Verification:** Next fetcher implementation that hits sandbox-blocked source returns a report instead of "ran out of turns."

### 2.2 Add `_ACQUISITION_PLACEHOLDER` flag to BaseFetcher
- **Files:** `claimweb/fetchers/base.py`
- **Action:** Add `acquisition_placeholder: bool = False` class attribute. Fetchers whose URLs have not been live-validated set this to True. Add a `validate()` warning when set.
- **Verification:** `naic_schedule_s.py` and `naic_schedule_d.py` declare `acquisition_placeholder = True` per Stage 3.

### 2.3 Create `acquisition-validator` agent
- **Files:** `.claude/agents/acquisition-validator.md` (new)
- **Action:** New subagent that runs from a non-sandbox environment to live-test a fetcher's URLs and update its `acquisition_placeholder` flag.
- **Verification:** Agent definition exists; example invocation produces a structured report.

### 2.4 Enforce `literature-checker` invocation in `reconstruction-author` skill
- **Files:** `.claude/skills/reconstruction-author/SKILL.md`
- **Action:** Make the literature-checker step a required precondition with explicit "do not proceed without subagent output."
- **Verification:** The skill description includes the mandate.

## Stage 3 — F1 Remediation and NAIC Placeholder-URL Replacement

Effort: 5-7 days. **Must complete before June 30, 2026** to use Iowa IID before sunset.

### 3.1 Flip arc direction in 9 fetchers
For each of `naic_schedule_d`, `sec_13f`, `sec_xbrl`, `sec_nmfp`, `fhlb_combined`, `frb_efa_fabs`, `z1`, `sec_adv` (G3 ownership convention to be reviewed separately):
- **Files:** `claimweb/fetchers/<fetcher>.py`
- **Action:**
  1. Swap `source_node_id` and `target_node_id` at every `ArcFact(...)` construction site.
  2. Update docstring "Arc direction" section to read "source = holder; target = issuer" matching kcl.py.
  3. Update `validate()` prefix checks (swap `source.startswith(...)` and `target.startswith(...)`).
  4. Update unit tests in `tests/unit/test_<fetcher>.py` that assert specific source/target prefix patterns.
- **Verification:** All 1,095 unit tests still pass after each fetcher's flip. CHANGELOG entry per fetcher documenting the inversion.

### 3.2 Verify naic_schedule_s is left unchanged
- **Files:** `claimweb/fetchers/naic_schedule_s.py`
- **Action:** No code change. Confirm with a unit test that an A6 arc emitted by Schedule S, joined into a one-arc network, satisfies KCL when `equity_millions = -dollar_amount_millions` at the source (cedent, asset holder) and `equity_millions = +dollar_amount_millions` at the target (reinsurer, liability issuer).
- **Verification:** New test in `test_naic_schedule_s.py` `TestKclCompatibility` passes.

### 3.3 Add an end-to-end fetcher→compile→KCL integration test
- **Files:** `tests/integration/test_phase1_kcl_endtoend.py` (new, marked `@pytest.mark.integration`)
- **Action:** Construct a small synthetic network combining one ArcFact from each fetcher's fixture; pass through `compile_constraints` and `check_kcl`; assert satisfied.
- **Verification:** The test passes. Marks the cross-module convention is settled.

### 3.4 NAIC Schedule S/D placeholder-URL investigation
- **Files:** none yet (research first)
- **Action:** Investigate from a non-sandbox environment whether `iid.iowa.gov` exposes Schedule S/D PDFs at a stable URL pattern. Iowa RIU portal sunsets June 30, 2026; identify the replacement path.
- **Verification:** A documented URL pattern in CHANGELOG; either a working acquisition path or a written acknowledgment that no free path exists for Schedule S/D and Phase 1 scope is reduced.

### 3.5 Update naic_schedule_s.py and naic_schedule_d.py with real URLs (if investigation succeeds)
- **Files:** `claimweb/fetchers/naic_schedule_{s,d}.py`
- **Action:** Replace placeholder `_IOWA_IID_BASE` URL with the live path discovered in 3.4. Set `acquisition_placeholder = False`. Add a `@pytest.mark.integration` test that fetches one filing.
- **Verification:** Integration test passes from a non-sandbox runner.

### 3.6 Scope reduction (if 3.4 fails)
- **Files:** `docs/PHASE_GATES.md`
- **Action:** Replace G1.09 criterion text to exclude Schedule S/D from "end-to-end" Phase 1 acquisition. Add a "Phase 1.5 — NAIC integration" carve-out per project plan §52 governance.
- **Verification:** User confirmation of the scope change.

## Stage 4 — Live-Data Validation for Unverified Fetchers

Effort: 3-4 days (one day per fetcher, plus a runner-setup day). Depends on Stage 2 (acquisition-validator agent).

### 4.1 Live-test `sec_13f.py`
- **Action:** From a non-sandbox runner, run `Sec13fFetcher().acquire(Period("2024-Q4"))` for one CIK in `_MANAGER_REGISTRY`. Verify the EDGAR submissions JSON downloads, the 13F-HR filing is found within the window, and the informationTable XML parses cleanly.
- **Verification:** A successful one-CIK acquisition; cache file present in `data/raw/sec_13f/2024-Q4/`. Set `acquisition_placeholder = False`.

### 4.2 Live-test `sec_adv.py`
- **Action:** Run `SecAdvFetcher().acquire(Period("2024-Q4"))`. Verify the IAPD bulk ZIP downloads and `ia_firm.csv` + `ia_schedule_r.csv` extract.
- **Verification:** Same.

### 4.3 Live-test `sec_nmfp.py`
- **Action:** Run `SecNmfpFetcher().acquire(Period("2024-Q4"))` (or 2024-12). Verify the EDGAR EFTS query returns N-MFP filings and the per-filing XML downloads.
- **Verification:** Same.

### 4.4 Document live-data validation in CHANGELOG
- **Files:** `CHANGELOG.md`
- **Action:** Append entries describing each successful live-data validation.
- **Verification:** CHANGELOG entries reference real cache files and timestamps.

## Stage 5 — Conservation-Law Compile Robustness

Effort: 1-2 days. Depends on Stage 3.

### 5.1 Add rank/conditioning check to `CompiledSystem.summary()`
- **Files:** `claimweb/constraints/compile.py`
- **Action:** Compute the rank and condition number of the assembled sparse matrix `A` (using `scipy.sparse.linalg.matrix_rank` or equivalent). Surface as `CompiledSystem.rank: int` and `CompiledSystem.condition_number: float`. Update `summary()` to include both.
- **Verification:** New unit test asserts: on a balanced synthetic network, rank equals `n_unknowns - n_free_parameters`; condition number below 1e10.

### 5.2 Add a property test: random synthetic networks satisfying all 4 laws by construction → compiled constraint satisfied to tolerance
- **Files:** `tests/unit/test_compile.py`
- **Action:** New property test using hypothesis to draw networks satisfying KCL+L2+L3+L4 simultaneously by construction; assert `compile_constraints` produces a feasible system.
- **Verification:** Test passes 100 examples.

## Stage 6 — Reference Quarter 2024-Q4 End-to-End

Effort: 2-3 days. Depends on Stage 3 (placeholders + flip) and Stage 4 (SEC live validation).

### 6.1 Run all 10 fetchers against 2024-Q4 from non-sandbox runner
- **Action:** Execute `Fetcher().run(Period("2024-Q4"))` for each of 10 fetchers; collect raw outputs to `data/raw/`; collect ArcFacts to `data/normalized/`.
- **Verification:** Every fetcher's `validate()` returns `is_clean=True` (or has only info-level issues).

### 6.2 Review unmapped-entity registries
- **Files:** `claimweb/registry/unmapped/*.json` (created at runtime)
- **Action:** Manually review each unmapped entity (corporates without CUSIP; reinsurers without NAIC code; etc.) and promote known mappings to the canonical per-fetcher registry.
- **Verification:** Re-run shows fewer unmapped entries; CHANGELOG documents promotions.

### 6.3 Re-run fetchers; capture final ArcFact set
- **Action:** Final fetcher pass with promoted mappings. Total ArcFact count.
- **Verification:** ArcFact count exceeds the project plan §1.2 implied minimum (every documented arc class A1-A12 has at least one record; sectoral aggregates match Z.1).

## Stage 7 — Reconstruction Implementation

Effort: 5-7 days. Depends on Stage 6.

### 7.1 Implement `claimweb.reconstruct.max_entropy`
- **Action:** Spawn `literature-checker` against Upper (2004) per `reconstruction-author` skill. Implement RAS / iterative proportional fitting. Cross-check on small subnetworks with cvxpy convex solver. Decimal-arithmetic precision at the boundary into the float solver per `.claude/rules/decimal-arithmetic.md`.
- **Verification:** Convergence on 2024-Q4 boundary terms; reconstructed network satisfies all 4 conservation laws within tolerance.

### 7.2 Implement `claimweb.reconstruct.min_density`
- **Action:** Spawn `literature-checker` against Anand-Craig-von Peter (2015). Implement the iterative algorithm with random restarts.
- **Verification:** Convergence; reconstructed network satisfies conservation laws; spread vs ME is positive (MD ≤ ME for each arc).

### 7.3 Implement `claimweb.reconstruct.solver` bracketing harness
- **Action:** Compose ME + MD; emit `BracketedNetwork` per arc with `(ME, MD, min, max)`.
- **Verification:** Bracketed output written to `data/output/network/2024-Q4/v1/`.

## Stage 8 — Sankey Visualization

Effort: 1-2 days. Depends on Stage 7.

### 8.1 Implement `claimweb.visualize.sankey`
- **Action:** Per `visualization-author` skill. Plotly-based renderer; arcs sized by dollar volume; nodes color-coded by ownership cluster; arc color by `DataQualityFlag` per `.claude/rules/data-quality-flags.md`.
- **Verification:** Static HTML artifact at `data/output/network/2024-Q4/v1/sankey.html`.

## Stage 9 — Methodology Paper Outline

Effort: 1-2 days. Independent of critical path; can begin immediately.

### 9.1 Draft `docs/METHODOLOGY.md` Phase 1 sections
- **Action:** Section structure: (a) Framework — node taxonomy, arc taxonomy, four conservation laws, the bracketing-of-ME-and-MD logic, the data-quality flags. (b) Fetcher architecture — BaseFetcher contract, per-source acquisition strategy, sandbox vs live-validated. (c) Reconstruction — Phases A-E from project plan §13. (d) Reference 2024-Q4 case — what arcs are present, what bracket is achieved, what conservation residual remains. Spawn `documentation-curator` agent to draft.
- **Verification:** File exists; outline matches project plan §35 expectations; Phase 1 sections only (Phases 2-5 reserved for later).

### 9.2 Document the Mistrulli nuance
- **Action:** Add a note in §Reconstruction that maximum entropy is not always the lower bound of contagion estimates; Mistrulli (2011) shows ordering can flip under some topologies.
- **Verification:** Citation present.

## Stage 10 — Phase 1 Closure Ceremony

Effort: 1 day. Depends on Stages 1-9.

### 10.1 Run `phase-gate-closer` skill
- **Action:** Verify every Phase 1 gate criterion in `docs/PHASE_GATES.md` is met. Run the conservation checker against the 2024-Q4 solved network. Capture verification artifacts.
- **Verification:** All 17 criteria show `- [x]`.

### 10.2 User confirmation event
- **Action:** Per project plan §52, surface the verified gate status to the user for explicit Phase 1 closure approval.
- **Verification:** User confirmation recorded in CHANGELOG.

### 10.3 Milestone commit
- **Action:** Tag the closure commit as `phase-1-close`; push tags.
- **Verification:** `git tag -l 'phase-*'` shows the tag.

---

## Out of scope for this remediation

Per project plan §52, the following are NOT in scope for Phase 1 closure and should not be attempted in the Stage 1-10 work:

- **Historical reconstruction** (2000-Q1 through 2023-Q4) — Phase 2.
- **Cascade simulation** (Eisenberg-Noe, fire sale, multi-constraint, contingent, DebtRank) — Phase 2.
- **Historical validation** (2007 XFABS, 2008 AIG, 2020 stress) — Phase 3.
- **ABM layer** — Phase 3.
- **External review and journal submission** — Phases 4-5.
- **Paid NAIC IDP subscription** — violates origin-data-only rule per CLAUDE.md.

## Verification scaffolding (Stage 10b in audit prompt)

The remediation requires verification primitives not currently in trunk. They become available as a side effect of Stage 4 (non-sandbox runner) and Stage 5 (rank check). Specifically:

- **Non-sandbox runner with network access** — user's Tesla workstation per project plan §20. Required for Stages 3-7.
- **`@pytest.mark.integration` runner config** — already declared in `pyproject.toml:73`. Stage 3.3 adds the first cross-fetcher integration test.
- **Live-data fixture repository** — separate from `tests/fixtures/`; captures small live-acquired snapshots for regression. Created during Stage 4.
- **`make all` target** — per project plan §46; not in scope until Phase 1 closes and reproducibility-package work begins (Phase 3 deliverable per PHASE_GATES.md L70).
- **`verify.py`** — same; Phase 3 deliverable.

## Estimated total effort

| Stage | Days |
|---|---:|
| 1. Documentation reconciliation | 1 |
| 2. Subagent reliability | 1-2 |
| 3. F1 + NAIC placeholder | 5-7 |
| 4. SEC live validation | 3-4 |
| 5. Compile robustness | 1-2 |
| 6. Reference 2024-Q4 | 2-3 |
| 7. Reconstruction | 5-7 |
| 8. Sankey | 1-2 |
| 9. Methodology (parallel) | 1-2 |
| 10. Phase 1 closure | 1 |
| **Total critical path** | **~21-30 days** |

Roughly 4-6 weeks of focused operator time. **The Iowa RIU portal sunset on June 30, 2026 is the binding constraint** — Stage 3 must execute first.
