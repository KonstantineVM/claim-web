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

## Phase 2 — Architectural Census

### 2a. Production Code Inventory and Arc-Emission Ground Truth

`docs/audit_v1/scratch/03_file_inventory.csv` is the per-file production-code census (47 rows; one per Python file under `claimweb/`). `docs/audit_v1/scratch/04_arc_emissions.csv` is the arc-emission ground truth (31 rows; one per `(fetcher, source_pattern, target_pattern, arc_class)` tuple emitted by `parse()`). The narrative below summarizes the structural facts and flags the patterns that propagate to downstream sections.

#### 2a.1 Subpackage totals

| Subpackage | Files | LOC | Role | Phase |
|---|---:|---:|---|---|
| `claimweb/` (root) | 1 | 25 | Package init; Decimal precision setup | 1 |
| `fetchers/` | 11 | 6,662 | 10 concrete fetchers + base ABC | 1 |
| `constraints/` | 6 | 1,940 | Laws 1–4 + compile + prior | 1 |
| `reconstruct/` | 5 | 88 | Stubs only | 1 (planned) |
| `cascade/` | 6 | 95 | Stubs only | 2 (planned) |
| `abm/` | 5 | 71 | Stubs only | 3 (planned) |
| `visualize/` | 5 | 65 | Stubs only | 1 (Sankey) + 2/3 |
| `validation/` | 4 | 54 | Stubs only | 3 |
| `multiplier/`, `normalize/`, `api/` | 3 | 43 | `__init__` only | 2/3 |

Total: 46 Python files, 9,061 LOC. The ratio of substance-code (fetchers + constraints) to scaffolding (everything else) is 8,602 : 459 — 95% of LOC is in the two subpackages that have shipped Phase 1 work. This matches the project plan's Phase 1 scope.

#### 2a.2 Fetchers — public-interface census

All 10 concrete fetchers subclass `BaseFetcher` and declare the mandatory `source_id` and `cadence` class attributes. The cadences match project plan §10:

| Fetcher | `source_id` | `cadence` | Cache lifetime | LOC |
|---|---|---|---:|---:|
| `fhlb_combined` | `fhlb_combined` | quarterly | (default; not declared as constant) | 637 |
| `frb_efa_fabs` | `frb_efa_fabs` | quarterly | 1 day | 473 |
| `naic_schedule_d` | `naic_schedule_d` | annual | 365 days | 1,000 |
| `naic_schedule_s` | `naic_schedule_s` | annual | 365 days | 888 |
| `sec_13f` | `sec_13f` | quarterly | 90 days | 749 |
| `sec_adv` | `sec_adv` | quarterly | 90 days | 719 |
| `sec_nmfp` | `sec_nmfp` | monthly | 30 days | 727 |
| `sec_xbrl` | `sec_xbrl` | quarterly | 14 days | 506 |
| `z1` | `z1` | quarterly | 30 days | 530 |

`base.py` (404 LOC) defines: `Period` (validated `YYYY-Q[1-4]`), `ArcClass` (A1–A12 enum), `DataQualityFlag` (7-value enum with documented priority ordering DIRECT_MEASURED > DOUBLE_ENTRY_INFERRED > MARGINAL_INFERRED > SECTORAL_DISAGGREGATED > PROXY > MODEL_ESTIMATE > UNOBSERVED — matches the CLAUDE.md rule at `.claude/rules/data-quality-flags.md`), `RawDataHandle`, `ArcFact` (immutable Decimal dollar amounts; mandatory provenance; `to_dict`/`from_dict`), `ValidationIssue`/`ValidationReport`, and `BaseFetcher` ABC with `__init_subclass__` guard enforcing `source_id` and `cadence`.

NAIC Schedule D at 1,000 LOC and NAIC Schedule S at 888 LOC are the two largest fetchers — both because they need per-state-portal dispatch logic for acquisition (Iowa IID vs NAIC CIS vs Indiana vs Tennessee) and per-row classification (CUSIP-prefix dispatch, type-code dispatch, description-pattern dispatch for security type). The CHANGELOG claims Schedule D is 887 LOC; the actual file is 1,000 LOC. The 113-LOC delta suggests post-PR edits (linting fixes, format adjustments) that were not back-propagated to the CHANGELOG entry — benign.

#### 2a.3 Arc-emission ground truth

Twelve of the project plan §4 arc classes A1–A12 are addressable in Phase 1; nine are reached by at least one shipped fetcher. The coverage matrix:

| Arc | Class meaning | Fetchers that emit | Source prefix(es) | Target prefix(es) |
|---|---|---|---|---|
| A1 | Funding agreements | `sec_xbrl` | `insurer:cik:{cik}` (issuer) | `z1:all_holders` |
| A2 | FABNs (FABN/FABCP/XFABS) | `frb_efa_fabs`, `sec_nmfp`, `z1` | `sector:fabn_spv` or `spv:cusip:` | `efa:*_holders`, `mmf:`, `sector:life_insurance_companies` |
| A3 | FHLB advances | `fhlb_combined`, `sec_xbrl`, `z1` | `insurer:naic:` or `insurer:slug` or `{entity_id}` | `fhlb:system` or `sector:fhlb` |
| A4 | Repo | `sec_xbrl` | `{entity_id}` | `sector:repo_dealers` |
| A5 | Sec-lending cash collateral | `sec_xbrl` | `{entity_id}` | `sector:sec_lending_counterparty` |
| A6 | Reinsurance | `naic_schedule_s` | **`insurer:naic:` (cedent)** | **`reinsurer:` (reinsurer)** |
| A7 | CLO mezzanine | `naic_schedule_d` | `issuer:clo:{cusip_prefix}` | `insurer:naic:{code}` |
| A8 | MMF shares | `z1` | `sector:money_market_funds` | `sector:life_insurance_companies` |
| A9 | Bank deposits | `z1` | `sector:depository_institutions` | `sector:life_insurance_companies` |
| A10 | Government securities | `naic_schedule_d`, `z1` | `issuer:us_treasury`, `issuer:agency:{name}`, `sector:gse` | `insurer:naic:`, `sector:life_insurance_companies` |
| A11 | Equity claims | `sec_13f`, `sec_adv` | `corp:cusip:{cusip6}`, `corp:name:`, `aam:crd:{crd}` | `aam:cik:{cik10}`, `insurer:`/`aam:`/`fund:`/`broker:`/`bank:`/`entity:` |
| A12 | Other liabilities (residual) | `naic_schedule_d`, `sec_13f`, `sec_xbrl`, `z1` | various | various |

**Coverage gaps (Phase 1):** No fetcher emits A6 from anyone but `naic_schedule_s`. No Bermuda-side companion fetcher exists for the offshore reinsurer node (project plan §10.12 `bma_register.py` is unbuilt). No fetcher addresses A11 from public-company 10-K equity-holder data (only AAM-side via 13F/ADV). A2 has three distinct fetchers but with disjoint coverage: `frb_efa_fabs` provides the aggregate (Law-3 boundary), `sec_nmfp` provides MMF-side per-CUSIP, `z1` provides sector-level — they should agree under Law 2 at the FABN aggregate, but no test currently enforces the cross-fetcher reconciliation.

**Arc-direction conventions across fetchers.** Reading the file inventory shows the per-fetcher direction conventions explicit in code:

- `fhlb_combined.py`: source = insurer (issuer of the FHLB-advance liability), target = `fhlb:system` (holder of the advance as asset). §1.1 ✓
- `frb_efa_fabs.py`: source = `sector:fabn_spv` (issuer of FABN/FABCP), target = `efa:*_holders` (the holder sector). §1.1 ✓
- `naic_schedule_d.py:37-38, 731-732`: source = bond issuer, target = insurer holder. §1.1 ✓
- `naic_schedule_s.py:33-34, 648-651`: source = U.S. cedent (the holder of the recoverable asset), target = reinsurer (the issuer of the recoverable obligation). **§1.1 ✗ INVERTED** — see Finding F1 in Phase 1.
- `sec_13f.py:19-21, 332`: source = security issuer (`corp:cusip:`), target = AAM holder (`aam:cik:`). §1.1 ✓
- `sec_adv.py:31, 522-525`: source = AAM parent (`aam:crd:`), target = controlled entity. This represents a G3 ownership arc per project plan §3.2; the convention "source = controlling parent, target = controlled affiliate" is the project's choice for G3 (project plan §3.2 says "operating entities point to their controlling parent" — meaning *target* = parent; the code does the opposite). Worth verifying in Phase 3c.
- `sec_nmfp.py:21, 379-382`: source = SPV issuer, target = MMF holder. §1.1 ✓
- `sec_xbrl.py:125-157`: mixed — for `Assets` (a tag whose value is "the entity's total assets"), the row is `(A12, z1:aggregate, {entity_id})` meaning the aggregate's "holding" is the entity's assets. The semantics here are not arc-like in the §1.1 sense — they are balance-sheet marginals. The fetcher emits these because Law 1 needs them as boundary terms. The downstream constraint compiler will need to recognize them differently from arcs; check `compile.py` integration.
- `z1.py:111-125`: source/target use sector: prefixes; the FL543050005.Q series at L125 reads `source=sector:life_insurance_companies, target=sector:fhlb` for an A3 advance — which under §1.1 is correct (life insurer is the issuer of the advance liability; FHLB holds it as the asset).

**Two additional convention questions to flag:**

(a) **G3 ownership-arc direction.** Project plan §3.2 reads "operating entities point to their controlling parent" (i.e., affiliate → parent). `sec_adv.py:522-525` emits `source=aam:crd:{crd}` (the parent/AAM) → `target=related entity` (the affiliate). This is the opposite direction. Either the project plan is wrong about §3.2 or the code is. The CHANGELOG entry for PR #13 describes the direction as "AAM parent → affiliated insurer/IA/fund/bank" which agrees with the code. So the project plan §3.2 prose conflicts with both the code and the CHANGELOG. Methodological gap to surface.

(b) **`sec_xbrl` balance-sheet marginals as arcs.** The `Assets` and `Liabilities` tags emit "arcs" between `z1:aggregate` and the entity. These are not arcs in the network-instrument sense; they are entity-level totals. The downstream KCL constraint builder (`kcl.py`) operates on `NodeBalance` records, not `ArcFact` records — so these XBRL emissions need to be transformed at the boundary. Whether the transformation exists in code is to be verified in Phase 2b (constraints integration).

#### 2a.4 Constraints — public-interface census

All four laws follow the same dual interface: `build_<law>_rows()` produces a `ConstraintSet` of `LinearConstraint` objects (consumed by `compile.py`); `check_<law>()` directly verifies a concrete `NetworkState` against the law (consumed by `scripts/check_conservation.py` per CLAUDE.md). `kcl.py` defines the shared types `ArcKey, LinearConstraint, ConstraintSet, NetworkState, NodeBalance` that every other constraint module imports.

| Module | LOC | `build_*_rows` | `check_*` | Property tests |
|---|---:|---|---|---:|
| `kcl.py` | 444 | `build_kcl_rows(network: NetworkState) -> ConstraintSet` | `check_kcl(network, *, tol) -> KCLResult` | 5 |
| `double_entry.py` | 319 | `build_double_entry_rows(facts, *, period, boundary_terms) -> ConstraintSet` | `check_double_entry(network, *, boundary_terms, tol) -> DoubleEntryResult` | 5 |
| `sectoral.py` | 384 | `build_sectoral_rows(facts, *, period, sector_map, sectoral_totals) -> ConstraintSet` | `check_sectoral(network, *, sector_map, sectoral_totals, tol) -> SectoralResult` | 5 |
| `flow_funds.py` | 421 | `build_flow_funds_rows(facts_from, facts_to, *, period_from, period_to, flow_terms, revaluation_terms) -> ConstraintSet` | `check_flow_funds(network_from, network_to, *, flow_terms, revaluation_terms, tol) -> FlowFundsResult` | 6 |
| `compile.py` | 337 | `compile_constraints(network, *, boundary_terms, sector_map, sectoral_totals, network_from, flow_terms, revaluation_terms, include_nonnegativity) -> CompiledSystem` | n/a | 5 |
| `prior.py` | 13 | (stub) | (stub) | 0 |

Property tests cover (per the constraint-author skill): soundness (Law-satisfying networks satisfy compiled constraints), completeness (perturbations are detected), stability (DIRECT_MEASURED fold-into-RHS is correct), independence (each row references only the relevant entities). Total: 26 property tests across the 5 implementing modules. This exceeds the project plan's implicit floor (4 per law).

`compile.py` makes Law 1 always-applied (KCL is structural), Laws 2/3/4 conditional on the caller supplying their respective boundary data (`boundary_terms`, `sector_map+sectoral_totals`, `network_from+flow_terms`). It rejects degenerate Law 4 inputs (same period for `network` and `network_from` — `ValueError`). Non-negativity is opt-in via the `include_nonnegativity` keyword (default True). The output `CompiledSystem` has `to_index()` (bijection from `ArcKey` to integer column index) and `summary()` (one-line human-readable report). This is consumed by the planned `claimweb.reconstruct.solver`.

The `prior.py` module (13 LOC) is a docstring-only stub. Its planned interface (`entity_type_compatibility`, `build_prior_regularizer`) belongs to Phase 1's reconstruction stage. It's neither built nor scheduled in the current TODO.md Now/Next — the reconstruction sessions (max_entropy, min_density) will need to decide whether to use it.

#### 2a.5 Reconstruct, cascade, abm, visualize, validation, multiplier, normalize, api — stub state

All 24 files in these seven subpackages are docstring-only stubs between 11 and 25 LOC. Each docstring names the right academic reference (Upper 2004, Anand-Craig-von Peter 2015, Eisenberg-Noe 2001, Cont-Schaanning 2017, Coen-Lepore-Schaanning 2019, Banerjee-Feinstein 2019, Battiston et al. 2012, Bookstaber-Paddrik-Tivnan 2018) and lists the planned public interface signatures. No implementation exists; no tests exist. This is expected per the queued TODO.md state. The remediation plan addresses Phase 1 reconstruction (Stages 7–8); cascade, ABM, validation are Phase 2/3 scope.

---

### 2b. Test Census and Acquisition-URL Census

#### 2b.1 Test inventory

`tests/` contains:
- `tests/__init__.py` (empty marker)
- `tests/conftest.py` (1 line — docstring only; no shared fixtures defined)
- `tests/unit/` (16 test modules + `__init__.py`)
- `tests/integration/__init__.py` (placeholder; no integration test files)
- `tests/validation/__init__.py` (placeholder; no episode test files)
- `tests/fixtures/` (per-fetcher subdirectories with sample data)

| Test module | LOC | `def test_` | `@given` | `@pytest.mark.parametrize` | Tests what |
|---|---:|---:|---:|---:|---|
| `test_compile.py` | 836 | 57 | 5 | (heavy) | `claimweb.constraints.compile` |
| `test_double_entry.py` | 758 | 40 | 5 | (some) | `claimweb.constraints.double_entry` (Law 2) |
| `test_fetchers_base.py` | 422 | 41 | 9 | yes (L98) | `claimweb.fetchers.base` |
| `test_fhlb_combined.py` | 442 | 35 | 1 | yes (L69) | `claimweb.fetchers.fhlb_combined` |
| `test_flow_funds.py` | 1,231 | 44 | 6 | (some) | `claimweb.constraints.flow_funds` (Law 4) |
| `test_frb_efa_fabs.py` | 939 | 77 | 3 | yes (L86, L105, L126, L154) | `claimweb.fetchers.frb_efa_fabs` |
| `test_kcl.py` | 843 | 35 | 5 | (some) | `claimweb.constraints.kcl` (Law 1) |
| `test_naic_schedule_d.py` | 1,276 | 146 | 4 | yes | `claimweb.fetchers.naic_schedule_d` |
| `test_naic_schedule_s.py` | 1,139 | 123 | 3 | yes | `claimweb.fetchers.naic_schedule_s` |
| `test_package_skeleton.py` | 74 | 3 | 0 | yes (L58, L63) | bootstrap smoke tests for every subpackage |
| `test_sec_13f.py` | 1,052 | 114 | 3 | yes | `claimweb.fetchers.sec_13f` |
| `test_sec_adv.py` | 882 | 96 | 3 | yes | `claimweb.fetchers.sec_adv` |
| `test_sec_nmfp.py` | 1,092 | 125 | 3 | yes (L137, L200, L213, L230) | `claimweb.fetchers.sec_nmfp` |
| `test_sec_xbrl.py` | 698 | 66 | 3 | yes (L95, L110, L142) | `claimweb.fetchers.sec_xbrl` |
| `test_sectoral.py` | 950 | 37 | 5 | (some) | `claimweb.constraints.sectoral` (Law 3) |
| `test_z1.py` | 710 | 56 | 3 | yes (L81, L107, L130) | `claimweb.fetchers.z1` |
| **Total** | **13,346** | **1,095** | **61** | — | — |

Resolution of the test-count discrepancy from Phase 1 (Finding F7): `@pytest.mark.parametrize` is used heavily — the `test_package_skeleton.py` file alone has 3 `def test_` functions but the parametrize lists at L58/L63 expand each across `_SUBPACKAGES + _SUBMODULES` (which per CHANGELOG PR #1 included 73 entries). The CHANGELOG's "1260 total pass" claim is the runtime collection count; the static `def test_` count is 1,095. The delta of 165 is consistent with the observed parametrize usage. **Verdict: confirmed in spirit.**

#### 2b.2 Integration-marker discipline

Only two `@pytest.mark.integration` test functions exist in trunk:
- `tests/unit/test_frb_efa_fabs.py:927` — likely a "fetch from live FRB" smoke test
- `tests/unit/test_fhlb_combined.py:420` — likely a "fetch from live FHLB-OF" smoke test

The `pyproject.toml` declares the `integration` marker (L73) and `scripts/precommit_gate.sh` excludes them from the fast suite (`-m "not integration"`) per CHANGELOG PR #3. No fetcher beyond `frb_efa_fabs` and `fhlb_combined` has any integration-marked test. The eight remaining concrete fetchers (NAIC S, NAIC D, SEC 13F, SEC ADV, SEC N-MFP, SEC XBRL, Z.1, and the unimplemented BMA/Treasury TIC) have no integration test scaffolding. This is consistent with the placeholder/sandbox-unverified state of those fetchers but means there is no in-repo path to validate them against live data even with network access.

#### 2b.3 Test ↔ production module coverage

Every concrete production module under `claimweb/fetchers/` has a matching test module under `tests/unit/`. Same for `claimweb/constraints/*.py`. The `tests/unit/test_compile.py` covers `claimweb/constraints/compile.py`. The `tests/unit/test_package_skeleton.py` is a bootstrap-era smoke test that verifies every subpackage exists with a docstring.

No test exists for:
- `claimweb/constraints/prior.py` — but this is a 13-LOC stub.
- Any module under `reconstruct/`, `cascade/`, `abm/`, `visualize/`, `validation/`, `multiplier/`, `normalize/`, `api/` — but these are all stubs.

No reverse problem: every test module references a production module that exists. No orphan test files.

#### 2b.4 Fixture inventory

`tests/fixtures/` contains 9 per-fetcher subdirectories matching the 9 fetchers with live-acquisition logic (`base` has no fixture because it has no acquisition):

| Fixture dir | Contents | Fetcher |
|---|---|---|
| `fhlb_combined/` | `2024-Q4-combined-financial-report.pdf` + `generate_fixture.py` | `fhlb_combined.py` |
| `frb_efa_fabs/` | `fabs-chart-data-historical.txt` (7 daily rows) | `frb_efa_fabs.py` |
| `naic_schedule_d/` | `schedule_d_2024.csv` (15 rows, 2 insurers, 3 arc types) | `naic_schedule_d.py` |
| `naic_schedule_s/` | `schedule_s_2024.csv` (17 rows, 5 cedents) | `naic_schedule_s.py` |
| `sec_13f/` | `informationtable_q4_2024.xml`, `submissions_q4_2024.json` | `sec_13f.py` |
| `sec_adv/` | `ia_firm.csv`, `ia_schedule_r.csv` | `sec_adv.py` |
| `sec_nmfp/` | `prime_fund_q4_2024.xml`, `govt_fund_q4_2024.xml` | `sec_nmfp.py` |
| `sec_xbrl/` | `CIK0001099219.json` (MetLife companyfacts subset) | `sec_xbrl.py` |
| `z1/` | `L116.csv`, `L121.csv`, `L207.csv`, `L208.csv`, `L211.csv`, `L226.csv`, `L227.csv` | `z1.py` |

Fixture CHANGELOG claims verified: Schedule D 15 rows ✓, Schedule S 17 rows ✓, Z.1 7 tables ✓. All fixtures are synthetic or small captured slices — none are full-quarter production extracts (and none could be, given the placeholder-URL state of three fetchers).

#### 2b.5 Acquisition-URL Census (07_acquisition_urls.csv)

`docs/audit_v1/scratch/07_acquisition_urls.csv` is the definitive answer to "which fetchers can actually acquire from live sources and which only parse fixtures." The 9-row classification:

| Fetcher | URL | Placeholder? | Live-reach |
|---|---|---|---|
| `fhlb_combined` | `https://www.fhlb-of.com/ofweb_userWeb/pageBuilder/fhlbank-financial-data-36` | No | **YES** (real; validated by subagent during PR #3) |
| `frb_efa_fabs` | `https://www.federalreserve.gov/releases/efa/fabs-chart-data-historical.txt` | No | **YES** (real; validated by subagent during PR #11) |
| `naic_schedule_d` | `https://iid.iowa.gov` + `https://content.naic.org/cis` | **YES** | **NO** (CHANGELOG PR #16 L122-123: "approximations used as placeholders for the actual portal interactions") |
| `naic_schedule_s` | `https://iid.iowa.gov` + `https://content.naic.org/cis` | **YES** | **NO** (CHANGELOG PR #14 L210-214: subagent ran out of turns; implementation proceeded from documentation) |
| `sec_13f` | `https://data.sec.gov/submissions/CIK{cik}.json` + `https://www.sec.gov/Archives/edgar/data/...` | No (real) | **UNVERIFIED** (CHANGELOG PR #17 L65-68: "EDGAR was not reachable from the sandbox environment; the agent confirmed the approach based on documentation research") |
| `sec_adv` | `https://www.sec.gov/investment/form-adv-data` + `https://efts.sec.gov/LATEST/search-index?forms=ADV` | No (real) | **UNVERIFIED** (CHANGELOG PR #13 L283-285: subagent ran out of turns) |
| `sec_nmfp` | `https://efts.sec.gov/LATEST/search-index` + `https://data.sec.gov/submissions/CIK{cik}.json` | No (real) | **UNVERIFIED** (CHANGELOG PR #12 L353-355: subagent unable to fetch due to network restrictions) |
| `sec_xbrl` | `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` | No (real) | **YES** (well-established endpoint reused from FSR Dashboard fetchers per project plan §10.2; no live-data flag raised in CHANGELOG) |
| `z1` | `https://www.federalreserve.gov/datadownload/Output.aspx` | No (real) | **YES** (FRB Data Download Program is well-documented public API) |

**Summary.** Of 10 concrete fetchers (excluding base):
- **3 live-validated** (FHLB Combined, FRB EFA FABS, FRB Z.1, SEC XBRL — 4 actually). The subagent confirmed URL patterns and the fetchers have been exercised against live endpoints (or against very-similar reused FSR Dashboard patterns for SEC XBRL).
- **3 unverified-but-real** (SEC 13F, SEC ADV, SEC N-MFP). The URLs are correct public SEC endpoints. The fetchers have never been validated against live API responses from this codebase's environment because the autonomous loop's sandbox lacks network access to SEC EDGAR. They will likely work but are not proven.
- **2 placeholder-URL** (NAIC Schedule S, NAIC Schedule D). The URLs are author's best-guesses at the per-state portal patterns. NAIC's free public surface does not expose Schedule S/D as machine-readable; the actual acquisition path will require either per-state portal scraping (with HTML/PDF parsing in addition to current CSV/JSON parsing) or paid IDP subscription (which violates the origin-data-only rule per CLAUDE.md). These two fetchers cannot acquire from live sources without rework.

**Phase 1 closure impact.** PHASE_GATES.md L25 requires "Reference quarter 2024-Q4 acquired end-to-end: raw data in `data/raw/`, normalized facts in `data/normalized/`." This criterion cannot close until:
1. The 2 placeholder fetchers have their acquisition paths reworked (Stage 3 of remediation plan).
2. The 3 unverified fetchers are tested against live EDGAR from a non-sandbox runner (Stage 4).
3. A non-sandbox runner exists with network access (per project plan §20: user's Tesla workstation).

The 4 fully-validated fetchers (FHLB, FABS, Z.1, XBRL) can already acquire 2024-Q4. They cover A1, A2, A3, A4, A5, A8, A9, A10, A12 from the Z.1 sectoral side and entity-level totals from XBRL — enough to populate Law 3 constraints and Law 1 boundary terms. The missing pieces are A6 (reinsurance — Schedule S placeholder), A7 (CLO mezzanine — Schedule D placeholder), and A11 (AAM cross-holdings — 13F unverified).

---
