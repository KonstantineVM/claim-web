# CLAIM-WEB Audit v1: Phase 1 Readiness Reckoning

## Header

- **Audit-start SHA:** `f2539805e5984f8e1b3fc02cf4b0ad316e740bce`
- **Audit branch:** `claude/audit-claim-web-q6ojZ` (the audit-execution prompt requested `audit/v1`, but the session-start hook pins the branch to `claude/audit-claim-web-q6ojZ` — work is performed on the harness-designated branch and the PR title preserves the intended `Audit v1` label)
- **Audit-start UTC:** 2026-05-15
- **Repository:** `github.com/KonstantineVM/claim-web` (default branch `main`)
- **Working tree at start:** clean; 149 committed files
- **Phase scope:** Phase 1 readiness only — does the trunk satisfy the criteria in `docs/PHASE_GATES.md` for closing Phase 1?

This audit is a static reading of committed contents. No fetcher was executed against a live data source; no reconstruction solver was run; no test was executed. Every claim below either (a) cites a file path and line range that the reader can verify directly or (b) is explicitly labeled "unverifiable from static reading."

The audit is organized in twelve phases per the prompt §6. Each phase is committed as its own commit on `claude/audit-claim-web-q6ojZ` and appended to this file. Intermediate scratch artifacts live in `docs/audit_v1/scratch/`.

The companion document `docs/AUDIT_REMEDIATION_PLAN_v1.md` is the sequenced operator-facing plan for closing every gap before Phase 1 gate closure. The report identifies gaps; the plan closes them.

---

## Phase 1 — Claim-vs-Reality Triage

### 1a. Claim Ledger

`docs/audit_v1/scratch/02_claim_ledger.csv` is the exhaustive ledger: 50 load-bearing claims compiled from `README.md`, `CLAUDE.md`, `CHANGELOG.md`, `TODO.md`, `docs/PHASE_GATES.md`, `docs/CLAIM_WEB_PROJECT_PLAN.md`, and the seventeen merged PR bodies (PR #1 through PR #17, excluding the closed PR #15). The columns are `claim_id, source_doc, location, claim_text, verification_method, verification_result, verdict`. The narrative below summarizes the verdicts and emphasizes the contradictions and disclosed placeholders that bear on Phase 1 closure.

The ledger groups into seven verdict categories:

| Verdict | Count | Meaning |
|---|---:|---|
| Confirmed | 22 | The claim is backed by file contents or commit history readable now. |
| Contradicted | 5 | The claim is demonstrably false against the current trunk. |
| Partially confirmed | 6 | The claim is partially supported; a portion is unverifiable from static reading. |
| Placeholder-Disclosed | 3 | The originating CHANGELOG entry acknowledges its own placeholder/unverified-against-live nature. |
| Stale/Ambiguous | 3 | The claim was true at some point but later commits or methodology drift make it ambiguous. |
| Open | 4 | The claim concerns a deliverable that does not yet exist. |
| To verify in Phase 2 | 7 | Routed to the architectural census phase because verification requires reading file bodies in detail. |

Total: 50. See `02_claim_ledger.csv` for the row-level evidence.

### 1b. Headline Findings

#### Finding F1 — A6 reinsurance arcs are inverted relative to project plan §1.1 (METHODOLOGICAL DEFECT)

This is the most consequential finding in Phase 1.

**The claim.** PR #14 (`ce89ed6`) ships `claimweb/fetchers/naic_schedule_s.py` emitting A6 reinsurance arcs. The fetcher's module docstring (file lines 32–34) states: "Arc direction (project plan §4, A6): source_node_id = U.S. cedent insurer (the party ceding reserves); target_node_id = offshore / domestic reinsurer (the party assuming reserves)." The CHANGELOG entry at L172–174 repeats this convention.

**The reality.** Project plan §1.1 at `docs/CLAIM_WEB_PROJECT_PLAN.md` L30 reads verbatim: "let $x_{ij}^k(t) \geq 0$ be the dollar volume of instrument $k$ that is held by $i$ as an asset and issued by $j$ as a liability at time $t$. This is the **arc weight** on the directed edge from issuer $j$ to holder $i$ for instrument $k$." That is: arc goes from $j$ (issuer) to $i$ (holder); source = issuer, target = holder.

For an A6 reinsurance recoverable: the *cedent* holds the recoverable on its balance sheet as an asset; the *reinsurer* has issued the contingent obligation and carries it as a liability. Under §1.1, $i$ = cedent and $j$ = reinsurer; the arc is reinsurer → cedent; source = reinsurer; target = cedent.

`claimweb/fetchers/naic_schedule_s.py` at L648–651 constructs `ArcFact(source_node_id=cedent_node, target_node_id=reins_node, ...)`. This is the opposite: **cedent → reinsurer**. The same direction appears in the documented convention and in the validate() function's prefix checks (file L707–719, which expect `source.startswith("insurer:")` and `target.startswith("reinsurer:")`).

**Cross-fetcher consistency check.** Every other Phase 1 fetcher emitting holding-side arcs follows §1.1 correctly:
- `naic_schedule_d.py:37-38` and L731 — source = bond issuer, target = insurer holder (§1.1 convention)
- `sec_13f.py:19-21` and L332 — source = security issuer (`corp:cusip:`), target = AAM holder (`aam:cik:`) (§1.1 convention)
- `fhlb_combined.py` (per CHANGELOG L835) and `z1.py` (per CHANGELOG L739) — source = insurer borrower (issuer of the advance liability), target = FHLB (holder of the advance asset) (§1.1 convention)

Schedule S is the lone outlier.

**Why this matters for Phase 1 closure.** Every downstream operation — constraint compilation (`compile.py`), KCL (`build_kcl_rows`), double-entry consistency (`build_double_entry_rows`), Z.1 sectoral disaggregation (`build_sectoral_rows`), reconstruction (`max_entropy`, `min_density`), cascade (`eisenberg_noe`) — assumes the §1.1 direction. Schedule S arcs with the inverted convention will violate Law 1 at every cedent and reinsurer node when joined into the network: a $100M cession will count as a $100M asset on the reinsurer's row and a $100M liability on the cedent's row, which is the opposite of statutory accounting. The conservation-law checker will flag every such arc unless the compiler accidentally re-inverts to the project-plan convention (the audit cannot verify this without execution).

The likely root cause is that the project plan §4 prose at L309 — "U.S. cedent transfers liability and underlying reserves to offshore reinsurer" — describes the *direction of value flow* (cedent ships reserves out; reinsurer receives them), and the PR #14 author read this as the arc direction. The author's reading is intuitive but inconsistent with §1.1, which defines the arc by who holds the *resulting claim*, not who shipped the value.

The remediation (Stage 3 in `docs/AUDIT_REMEDIATION_PLAN_v1.md`) is to invert the Schedule S source/target assignments, update the validate() prefix checks, update the docstring, and audit any test that depends on the direction. The closed PR #15 (per the audit prompt's recollection) appears to have used the §1.1 convention but was closed because it duplicated PR #14; verifying this requires checking GitHub's PR history.

#### Finding F2 — Placeholder acquisition URLs in three Phase 1 fetchers (DISCLOSED IN CHANGELOG)

Three fetchers explicitly disclose, in their PR's CHANGELOG entry, that the acquisition path is not live-validated:

1. **`naic_schedule_s.py`** (CHANGELOG L210–214): the `data-source-investigator` subagent ran out of turns. The Iowa IID URL pattern (`iid.iowa.gov/companies/{naic_code}/financials/{year}/schedule_s`, file L563) and the NAIC CIS pattern (file L562 surrounding) are inferred from project plan §10.3 and NAIC blank documentation. The fetcher parses fixtures correctly; it cannot acquire from a real NAIC source.

2. **`naic_schedule_d.py`** (CHANGELOG L122–123): the same investigator confirmed that NAIC does not have a public free JSON/XML/XBRL API for Schedule D Part 1 and that "the Iowa IID and NAIC CIS portal URLs in the fetcher are approximations used as placeholders for the actual portal interactions." Identical issue.

3. **`sec_13f.py`** (CHANGELOG L65–68): the investigator could not reach EDGAR from the sandbox; the SEC submissions-JSON URL pattern is real and well-documented, but the fetcher has never been validated end-to-end against live EDGAR data.

A fourth fetcher — `sec_nmfp.py` (CHANGELOG L353–355) — also had a network-blocked investigator and proceeded from documentation. Its EDGAR EFTS query URL is a real public endpoint, but live-acquisition was not exercised.

These are not bugs in the strict sense — the CHANGELOG flagged them at the time of authorship. They are, however, latent Phase 1 closure blockers: PHASE_GATES.md L25 requires "Reference quarter 2024-Q4 acquired end-to-end" and no fetcher with placeholder URLs can satisfy that criterion. See remediation Stages 3 and 4.

#### Finding F3 — PHASE_GATES.md is stale (DOCUMENTATION DRIFT)

`docs/PHASE_GATES.md` was last modified at the initial harness commit (visible in `git log -- docs/PHASE_GATES.md`). Of the 17 Phase 1 gate criteria listed at L17–33, **all are unchecked**. Yet:

- L17 "package skeleton exists with module-level docstrings" — closed by PR #1; every module has a docstring referencing its plan section.
- L18 "pyproject.toml exists with pinned dependencies" — closed by PR #1; `pyproject.toml` has the §19 stack.
- L19 "tests/ directory exists with pytest --collect-only running without error" — closed by PR #1.
- L20 "BaseFetcher abstraction in claimweb/fetchers/base.py implemented and unit-tested" — closed by PR #2.
- L21 "FhlbCombinedFetcher implemented end-to-end" — closed by PR #3.
- L22 "Z1Fetcher implemented for the seven L.tables" — closed by PR #5.
- L23 "SecXbrlFetcher implemented for the LIFE_INSURERS panel" — closed by PR #7.
- L24 "FrbEfaFabsFetcher implemented for the daily FABS dataset" — closed by PR #11.
- L26 "All four conservation-law constraint builders … with property-based hypothesis tests" — closed across PRs #4, #6, #8, #9 (KCL, double_entry, sectoral, flow_funds; 5 property tests each).
- L27 "ConstraintSet compile step implemented" — closed by PR #10 (`compile.py`, 337 LOC, 5 property tests).

The remaining seven criteria (L25 reference 2024-Q4 acquisition, L28–L30 reconstruction, L31 conservation-checker on the solution, L32 Sankey, L33 methodology paper outline) are genuinely open.

The drift means PHASE_GATES.md does not function as the source of truth its docstring claims it is. A reader picking up the file as the audit prompt instructs would conclude no Phase 1 work has shipped. The remediation (Stage 1 in the plan) is mechanical: replace the closed checkboxes with `- [x] (closed YYYY-MM-DD, commit <hash>)` per the convention at the top of the file.

#### Finding F4 — `docs/METHODOLOGY.md` does not exist (PROMISED-NOT-DELIVERED)

PHASE_GATES.md L33 names `docs/METHODOLOGY.md` as the Phase 1 drafting target. TODO.md L29 has it queued in the Next-slot list. The file does not exist (`ls docs/` returns three files: `CLAIM_WEB_PROJECT_PLAN.md`, `PHASE_GATES.md`, `REGULATORY_ARBITRAGE.md`). The `documentation-curator` subagent has not been invoked by any merged PR (negative finding: zero CHANGELOG entries reference the subagent). See remediation Stage 9.

#### Finding F5 — TODO.md "Done" commit hashes don't match `main` (BENIGN DOCUMENTATION DRIFT)

Every Done entry in TODO.md lists a commit hash. Spot-checked seven entries against `git log --oneline -25`:

| Item | TODO hash | Actual on `main` |
|---|---|---|
| sec_13f | `5c2de41` | `f253980` (PR #17 merge) |
| naic_schedule_d | `c8a3c14` | `00204b0` (PR #16 merge) |
| naic_schedule_s | `300265a` | `ce89ed6` (PR #14 merge) |
| sec_adv | `8486b14` | `8486b14` itself + `fa9b75e` (PR #13 merge) |
| sec_nmfp | `79851ec` | `1820c3b` (PR #12 merge) |
| frb_efa_fabs | `57a9562` | `ce5364c` (PR #11 merge) |
| constraints/compile | `7296c21` | `9dd18a1` (PR #10 merge) |

The TODO hashes are the *branch-side* commits — the autonomous loop recorded the SHA of its own work commit, before it was squash-merged or rebase-merged into `main`. The merge commits are different SHAs. This is consistent and harmless, but means a reader using TODO.md hashes to find work on `main` will get 404. The remediation (Stage 1) is to standardize the hashes to the merge SHAs after each merge.

#### Finding F6 — Subagent reliability is below the implicit project standard (SYSTEMIC PROCESS ISSUE)

The `fetcher-author` skill mandates spawning `data-source-investigator` before each fetcher's implementation. Counting CHANGELOG mentions across the 10 fetchers:

| Fetcher | Subagent state at PR time |
|---|---|
| `base` | not applicable (no external source) |
| `fhlb_combined` | success (confirmed URL pattern and PDF structure) |
| `z1` | not separately noted in CHANGELOG; fetcher works against FRB DDP |
| `sec_xbrl` | not separately noted; reused FSR Dashboard patterns |
| `frb_efa_fabs` | success (confirmed FABCP-quarterly-only, billions vs millions) |
| `sec_nmfp` | failed: network restrictions prevented EDGAR access |
| `sec_adv` | failed: ran out of turns |
| `naic_schedule_s` | failed: ran out of turns |
| `naic_schedule_d` | success (confirmed no free API; documented 2025 SSAP 43R break) |
| `sec_13f` | partial failure: EDGAR unreachable; documentation-only |

The `literature-checker` subagent has never produced a recorded artifact. TODO.md L20 has it queued for the next-up `claimweb.reconstruct.max_entropy` work, but the previous session that attempted max_entropy hit Anthropic's 15-routine-runs-per-day cap before completing. The `documentation-curator` subagent has zero CHANGELOG mentions.

The pattern is: fetchers for which the subagent could reach the source got proper investigation; fetchers for sandbox-blocked sources got documentation-only implementations and the CHANGELOG honestly disclosed this. This is not a process collapse — it is the autonomous loop's environmental constraint surfacing as a documented limitation. The remediation (Stage 2) updates the `data-source-investigator` agent definition with an explicit "documentation-only mode" that produces a structured report even when network is unavailable, and the `fetcher-author` skill mandates a `_ACQUISITION_PLACEHOLDER` flag on fetchers whose URLs have never been live-validated.

#### Finding F7 — Test counts at the static level differ from CHANGELOG runtime counts (BENIGN; verifies in spirit)

`grep -c "def test_" tests/unit/*.py` yields 1,095 across 16 test modules. CHANGELOG PR #17 entry claims "1260 total pass." The 165-test delta is most plausibly pytest parametrization (`@pytest.mark.parametrize` on a single `def test_X` generates multiple test instances at runtime). Per-PR property-based test counts in the CHANGELOG match static `@given` counts within 1 in all cases checked (compile: claim 4, actual 5; flow_funds: claim 5, actual 6; naic_schedule_d: claim 3, actual 4). The minor discrepancies indicate copy-paste counts written before the final test was added. None are material.

#### Finding F8 — Reconstruction, cascade, ABM, visualize, validation are stubs (CONFIRMED; EXPECTED)

Every file in `claimweb/reconstruct/`, `claimweb/cascade/`, `claimweb/abm/`, `claimweb/visualize/`, and `claimweb/validation/` is a docstring-only stub between 11 and 25 lines. The docstrings cite the right references (Upper 2004 for `max_entropy.py`, Anand-Craig-von Peter 2015 for `min_density.py`, Eisenberg-Noe 2001 for `eisenberg_noe.py`, etc.) and name the planned public interfaces. No implementation exists. This is consistent with Phase 1's queued state — these belong to Phase 1 (reconstruction) and Phases 2–3 (cascade, ABM, validation). The remediation plan (Stages 7–8) addresses the Phase 1 reconstruction implementations.

### 1b Summary Statistics

- Total claims indexed: 50
- Confirmed: 22 (44%)
- Contradicted: 5 (10%)
- Partially confirmed: 6 (12%)
- Placeholder-Disclosed: 3 (6%)
- Stale/Ambiguous: 3 (6%)
- Open / to-verify-in-Phase-2: 11 (22%)

The single Contradicted finding that requires *action* (not just documentation update) is F1 — Schedule S arc direction. F2's placeholder-URLs are disclosed but block Phase 1 closure. F3, F4, F5 are documentation drift fixable in Stage 1 of the remediation plan. F6 is a process improvement for the autonomous loop. F7, F8 are benign.

**Phase 1 closes with one substantive methodological defect (F1 — arc-direction inversion in Schedule S), three live-acquisition gaps (F2 — Schedule S, Schedule D, 13F), and four documentation-drift items (F3, F4, F5, F6).** The remaining unverifiable claims (live-data correctness, runtime-pass status) cannot be resolved without execution and are routed to the remediation plan's Stage 4 (live-data validation in a non-sandbox environment).

---
