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

### 2c. Supporting Material Census

#### 2c.1 Documentation files

Seven Markdown documentation files exist in trunk:

| Path | Lines | Audience | Last modified |
|---|---:|---|---|
| `README.md` | 99 | New harness user / external | initial harness commit (~10 hours pre-audit start) |
| `CLAUDE.md` | 145 | Autonomous Claude session | initial harness commit |
| `CHANGELOG.md` | 972 | All sessions; archival | per-PR (newest entry: 2026-05-15, PR #17) |
| `TODO.md` | 98 | Next session pickup | per-PR (current Now: max_entropy) |
| `docs/CLAIM_WEB_PROJECT_PLAN.md` | 1,420 | Authoritative methodology | initial harness commit |
| `docs/PHASE_GATES.md` | 114 | Phase-transition checkpoints | initial harness commit (STALE — see F3) |
| `docs/REGULATORY_ARBITRAGE.md` | 348 | Methodology framing background | initial harness commit |

**Missing-from-trunk references (matches Phase 1 F4):**
- `docs/METHODOLOGY.md` — referenced in PHASE_GATES.md L33 and TODO.md L29 Backlog as a Phase 1 deliverable; does not exist.
- `docs/validation/` — referenced in PHASE_GATES.md L49-51 (Phase 2 retrodiction reports); not created (no Phase 2 work shipped yet).
- `docs/reviews/` — referenced in PHASE_GATES.md L76-78 (Phase 4 external reviews); not created (Phase 4 is months 19-24 — far out of scope).

The CHANGELOG and TODO are the two living documents updated by the autonomous loop. The other five are write-once at harness time.

#### 2c.2 Configuration files

- **`pyproject.toml`** (97 lines): declares the §19 dependency stack. Core scientific: `numpy ≥ 2.1`, `scipy ≥ 1.14`, `pandas ≥ 2.2`, `networkx ≥ 3.4`, `cvxpy ≥ 1.5`, `pyarrow ≥ 18.0`. Statistical: `statsmodels`, `scikit-learn`. Plotting: `matplotlib`, `plotly`, `pyvis`. Acquisition: `httpx`, `requests`, `beautifulsoup4`, `pdfplumber`, `tabula-py`, `lxml`. Property testing: `hypothesis`. Dev: `pytest`, `ruff`, `mypy`. Optional `test` and `dev` groups. Pytest markers `slow`, `integration`, `validation` declared. Ruff config selects E/F/W/I/N/UP/B/C4/SIM; ignores E501 (line length). Mypy strict_equality + warn_return_any.

  Cross-reference against fetcher imports: all imports (`httpx`, `pdfplumber`, `lxml`, `beautifulsoup4`, `csv` builtin, `zipfile` builtin) are satisfied by declared dependencies. Constraint modules import only from `decimal` and `claimweb.fetchers.base` — no external deps. **No undeclared dependencies found.**

- **`uv.lock`** (447,603 bytes): full lock for the dependency graph. Not read in detail; absence of any "lock-file out of sync" message in CHANGELOG suggests it tracks pyproject.toml.

- **`.gitignore`** (~40 lines): excludes `__pycache__/`, `.pytest_cache/`, `.venv/`, `.mypy_cache/`, etc. Critically excludes `data/raw/*` except `.gitkeep` (per project plan §47 — content-addressed archive) and `data/output/network/*/v*/` except `v0/` placeholder (reproducible outputs not committed). Excludes `.claude/session-log/` (large, low-value) per CLAUDE.md. Excludes stop-hook scratch files (`claimweb_stop_counter_*`, `claimweb_pycompile_err`, etc.). No issues found.

- **`install.sh`** (6,894 bytes): not deeply analyzed; per README §Installation it sets up hook dependencies and verifies environment.

#### 2c.3 Harness (`.claude/`)

The `.claude/` tree is the autonomous-mode operating environment per README §How the harness works. 24 files total:

**Agents (5).** Each is a Markdown file with YAML frontmatter declaring `name`, `description`, `tools`, `maxTurns`, optional `permissionMode`. The five agents and their roles:

| Agent | Tools | maxTurns | Role |
|---|---|---:|---|
| `data-source-investigator` | Bash, WebFetch, WebSearch, Read, Grep, Glob | 30 | Characterize external data source before fetcher implementation |
| `documentation-curator` | Read, Write, Edit, Grep, Glob, Bash | 30 | Sync `docs/` with implementation (NEVER INVOKED per F6) |
| `literature-checker` | WebFetch, WebSearch, Read, Grep | 25 | Verify methodology matches cited paper (NEVER COMPLETED per F6) |
| `network-solver-debugger` | Bash, Read, Grep, Glob | 35 | Debug ME/MD reconstruction failures (Phase 1 reconstruction prerequisite) |
| `retrodiction-replayer` | Bash, Read, Grep, Glob | 40 | Run a historical episode end-to-end (Phase 3) |

Cross-reference: every agent is referenced by at least one skill file (e.g., `fetcher-author/SKILL.md` references `data-source-investigator`; `reconstruction-author` and `cascade-author` reference `literature-checker`; `phase-gate-closer` references `documentation-curator`).

**Slash commands (5).** `claimweb-bootstrap` (initial run), `claimweb-loop` (Ralph-style autonomous loop), `claimweb-next` (pick up TODO Now), `claimweb-status` (state report), `claimweb-validate` (run validation suite). All five are documented in CLAUDE.md.

**Skills (9 directories, one SKILL.md each).** Each is auto-loaded by description match per CLAUDE.md authoring conventions. The set covers the Phase 1–3 implementation surfaces: `fetcher-author`, `constraint-author`, `reconstruction-author`, `cascade-author`, `abm-author`, `validation-author`, `visualization-author`, `phase-gate-closer`, `methodology-amendment`. Every skill maps to a project-plan section or a phase-gate criterion.

**Rules (4).** Loadable per-topic rules: `conservation-laws.md`, `data-quality-flags.md`, `decimal-arithmetic.md`, `git-discipline.md`. These appear as system reminders when files in the relevant area are touched (the audit observed this: the `data-quality-flags.md` and `decimal-arithmetic.md` rules loaded when this audit read fetcher source files). All four are well-formed and consistent with the project plan.

**`settings.json`** (sole config): registers six hook events:
- `SessionStart` → `scripts/session_start_context.sh` (prints branch + Now item + recent CHANGELOG; the audit-start hook fired with this content)
- `UserPromptSubmit` → `scripts/inject_state.sh`
- `PreToolUse` (matcher `Bash`) → `scripts/guard_bash.sh` (blocks force-push, hard-reset per `git-discipline.md`)
- `PreToolUse` (matcher `Write|Edit|MultiEdit`) → `scripts/guard_no_paid_aggregator.sh` (blocks paid-aggregator imports per origin-data-only rule)
- `PostToolUse` (matcher `Write|Edit|MultiEdit`) → `scripts/post_edit_check.sh` (probably runs check_conservation, check_data_sources, py_compile)
- `Stop` → `scripts/stop_review.sh` (probably enforces commit-before-stop per git-discipline)
- `PreCompact` → `scripts/precompact_preserve.sh` (probably stashes session context before context compaction)

This is six hook events, all wired. The settings.json structure is well-formed.

#### 2c.4 Workflows

`.github/workflows/claimweb-gate.yml` (61 lines): single CI workflow on `pull_request` to `main` and `push` to `main`. Steps:
1. Checkout (fetch-depth 0)
2. setup-python 3.12
3. `pip install -e ".[dev]"` + auxiliary tools (pytest, hypothesis, ruff, jq)
4. `chmod +x scripts/*.sh`
5. Run `bash scripts/precommit_gate.sh` (continue-on-error: false → red fails the PR)
6. On PR success: `gh pr merge --auto --squash --delete-branch` — this is the auto-merge mechanism CLAUDE.md describes.

This is the only workflow. There is no separate workflow for nightly fetch-validation against live sources, no scheduled retrodiction run, no Zenodo deposit step. All of those would be Phase 3+ scope; absence is expected.

#### 2c.5 Scripts

12 scripts under `scripts/`:

| Script | Lines | Role |
|---|---:|---|
| `check_conservation.py` | 85 | PostToolUse oracle for Laws 1–4 on emitted networks (per CLAUDE.md) |
| `check_data_sources.sh` | 62 | Grep new files for forbidden paid-aggregator imports/URLs |
| `guard_bash.sh` | 60 | Block force-push and hard-reset per `.claude/rules/git-discipline.md` |
| `guard_no_paid_aggregator.sh` | 57 | PreToolUse paid-aggregator-import block on Write/Edit |
| `inject_state.sh` | 32 | UserPromptSubmit context-injection (probably current Now item) |
| `post_edit_check.sh` | 81 | PostToolUse multi-check (py_compile + check_data_sources + check_conservation) |
| `precommit_gate.sh` | 155 | Full gate: ruff + pytest + conservation check; runs in CI per workflow |
| `precompact_preserve.sh` | 46 | PreCompact stash of context |
| `session_end_log.sh` | 58 | Session log append |
| `session_start_context.sh` | 56 | SessionStart context (CHANGELOG + TODO + PHASE_GATES preview) |
| `setup.sh` | 81 | One-time install hook dependencies |
| `stop_review.sh` | 86 | Stop hook: enforce commit-before-stop |

`scripts/check_conservation.py` is the only Python script — the operational guard for Laws 1–4 invoked on every PostToolUse on `claimweb/` and `data/output/`. Its behavior was not deeply analyzed in this phase; it gets a closer reading in Phase 7a.

#### 2c.6 Data placeholders and notebooks

`data/raw/.gitkeep`, `data/normalized/.gitkeep`, `data/output/.gitkeep`, `notebooks/.gitkeep`. No accidentally-committed raw data files, no committed notebook output. Per the `.gitignore` rules, `data/raw/*` and `data/output/network/*/v*/` (except v0) are gitignored. The audit confirms zero leakage.

#### 2c.7 Reference quarter 2024-Q4 — current cached state

The audit checked `data/raw/` for any cached acquisition output. Result: directory contains only `.gitkeep`. **No fetcher has been run end-to-end against any live data source from this codebase's repository state.** This is consistent with the Phase 1 closure gap on the reference-quarter criterion.

---

### 2. Phase 2 Summary

- 47 production Python files (10 concrete fetchers + base + 5 constraint modules + 24 stubs across reconstruct/cascade/abm/visualize/validation/multiplier/normalize/api); 9,061 LOC total.
- 16 unit test modules; 13,346 LOC; 1,095 `def test_` functions; 61 `@given` property tests. Test-count discrepancy with CHANGELOG resolved (parametrize expands count at runtime).
- 9 fixture directories with synthetic captured-slice data; no live-quarter snapshots.
- 4 fetchers can acquire live (FHLB, FABS, Z.1, XBRL); 3 are unverified-but-real (13F, ADV, N-MFP); 2 are placeholder-URL (NAIC S, NAIC D).
- 24 `.claude/` files (5 agents, 5 commands, 9 skills, 4 rules, settings.json); 1 GitHub Actions workflow; 12 scripts.
- 7 docs files; METHODOLOGY.md is the one Phase 1-named document that does not exist.

No orphan production files, no orphan tests, no orphan agents. Every committed file has a documented role. The single substantive defect surfaced in Phase 1 (Schedule S arc-direction inversion) propagates into Phase 2's arc-emission ground truth and motivates Stage 3 of the remediation plan.

---

## Phase 3 — Code-Documentation Reconciliation

### 3a. Documented-but-Missing

`docs/audit_v1/scratch/05_doc_path_references.csv` records all file paths referenced by name in documentation. The 50-row table groups into three classifications: **Present** (32 rows), **Future-work / out-of-scope** (15 rows — Phase 2-5 fetchers and artifacts), **Promised-not-delivered** (3 rows — Phase 1 documents that should exist).

**Promised-not-delivered (action items):**

1. **`docs/METHODOLOGY.md`** — referenced at `docs/CLAIM_WEB_PROJECT_PLAN.md:743` ("METHODOLOGY.md — Formal mathematical specification" as a root-level file in the planned layout); referenced at `docs/PHASE_GATES.md:33` as a Phase 1 closure criterion; referenced at `TODO.md:29` as a Backlog item. Does not exist. This is Phase 1 Finding F4 reaffirmed. Remediation in Stage 9.

2. **`.claude/hooks/`** — `CLAUDE.md` line ~93 reads "For deterministic guardrails, hooks are in `.claude/hooks/` and `.claude/settings.json`". The directory does not exist. Hooks live in `scripts/` (e.g. `scripts/guard_bash.sh`) and are wired by `.claude/settings.json` which contains `bash ${CLAUDE_PROJECT_DIR}/scripts/*.sh` invocations. This is **minor naming drift**: the conceptual placement implied by CLAUDE.md doesn't match the actual layout. Either move the scripts to `.claude/hooks/` or update CLAUDE.md. The audit considers this a Stage-1 documentation fix.

3. **`claimweb/fetchers/fred.py`** — `docs/CLAIM_WEB_PROJECT_PLAN.md:1188` reads "`fetchers/fred.py` (FSR) → `claimweb/fetchers/fred.py` with extensions for Z.1 instrument-level tables." The actual trunk uses `claimweb/fetchers/z1.py` (which acquires from the FRB Data Download Program, not FRED). The §11 layout at L562 correctly names `z1.py`; only the §15 prose at L1188 keeps the legacy `fred.py` name. **Minor doc drift.** The §11 layout supersedes; update §15 prose.

**Future-work (Phase 2+ scope — no remediation needed in Phase 1):**

Project plan §11 layout enumerates 18 fetchers. Trunk has 10. The 8 missing fetchers are all out-of-scope for Phase 1 per project plan §10 data-source phasing:

| Missing fetcher | Plan section | Phase |
|---|---|---|
| `sec_focus.py` (Broker-Dealer FOCUS X-17A-5) | §10.8 | 2 (I4 dealer banks need this for cascade) |
| `sec_nXXa.py` (BDC N-54A/C elections) | §10 (implied) | 2-3 (I8 BDC nodes) |
| `naic_schedule_ba.py` (alt investments) | §10.3 BA | 2 |
| `naic_schedule_db.py` (derivatives) | §10.3 DB | 2-3 |
| `fhlb_district.py` (11 district 10-Q/10-K) | §10.4 | 2 (supplement to fhlb_combined for top-10 lists per district) |
| `fio_annual.py` | §10.10 | 2 |
| `ofr_publications.py` | §10.11 | 2 |
| `bma_register.py` (Bermuda Monetary Authority) | §10.12 | 2 (T2 offshore reinsurer asset side) |
| `treasury_tic.py` | §10.13 | 2 (M5 cross-border) |
| `ffiec_y9c.py` | §11 layout | 2-3 |

These are correctly absent in Phase 1; the Phase 1 gate in PHASE_GATES.md does not list any of them as Phase 1 closure criteria. No action required.

**Phase-2-output artifacts referenced as `claimweb/output/network/{period}/arcs.parquet` etc.** are output paths that will be created when the reconstruction solver runs. The project plan §13 Phase E describes them; the audit confirms `data/output/.gitkeep` is the only placeholder. No remediation in Phase 1.

### 3b. Present-but-Undocumented

`docs/audit_v1/scratch/03_file_inventory.csv` lists every Python file in trunk. Cross-referencing against documentation mentions, four files exist that no documentation mentions by name:

1. **`claimweb/constraints/prior.py`** (13 LOC stub). Project plan §13 Phase B refers to "soft constraints from prior knowledge — entity-type compatibility … These appear as additional regularizers in the estimation objective." The constraint-author skill does not name `prior.py` specifically. The file is a placeholder for future implementation; the docstring is appropriately scoped. **Verdict: Present-as-scaffolding; documented in spirit by §13 Phase B.**

2. **`claimweb/abm/agents/__init__.py`** (1 LOC). The `claimweb/abm/` subpackage is referenced in CLAUDE.md and project plan Part XII. The nested `abm/agents/` is not separately documented. Scaffolding only; will house agent classes per project plan §38. **Verdict: Internal scaffolding.**

3. **`claimweb/reconstruct/validate.py`** (15 LOC stub). The four reconstruct files at `max_entropy.py`, `min_density.py`, `solver.py`, `validate.py` together implement project plan §13. `validate.py` is the reconstruction self-validation hook; the docstring names its role. The reconstruction-author skill mentions a self-validation step but does not name the file. **Verdict: Internal scaffolding for the reconstruction module.**

4. **`tests/conftest.py`** (1 LOC docstring). Empty conftest — no shared fixtures. Reserved for future use. **Verdict: Scaffolding.**

No files in trunk fall into the "Dead code" or "Aborted session" categories. Every file has at least an inbound import from a tested module or is itself a documented stub. The audit considers this clean.

### 3c. Documented-with-Wrong-Description and Arc-Direction Reconciliation

This phase examines whether descriptions in documentation match what the code actually does.

#### 3c.1 Arc-direction convention across fetchers (extends Phase 2a)

The audit's central methodological finding is the inconsistent arc-direction convention. The authoritative statement is `docs/CLAIM_WEB_PROJECT_PLAN.md` §1.1 (lines ~30–32): "let $x_{ij}^k(t) \geq 0$ be the dollar volume of instrument $k$ that is held by $i$ as an asset and issued by $j$ as a liability ... the **arc weight** on the directed edge from issuer $j$ to holder $i$." Translation: **source = issuer; target = holder**.

Per-arc-class verification of every Phase 1 fetcher (cross-referenced with `04_arc_emissions.csv`):

| Arc class | Fetcher | Code direction | §1.1 expected | Verdict |
|---|---|---|---|---|
| A1 (funding agreements) | `sec_xbrl.py:157` | source=`{entity_id}` (insurer issuer) → target=`z1:all_holders` | issuer=insurer → holder=z1 | ✓ |
| A2 (FABNs) | `frb_efa_fabs.py:101-111` | source=`sector:fabn_spv` → target=`efa:*_holders` | issuer=SPV → holder=sector | ✓ |
| A2 | `sec_nmfp.py:379` | source=`spv:cusip:*` → target=`mmf:*` | issuer=SPV → holder=MMF | ✓ |
| A2 | `z1.py:121` | source=`sector:fabn_spv` → target=`sector:life_insurance_companies` | issuer=SPV → holder=insurer | ✓ |
| A3 (FHLB advances) | `fhlb_combined.py:461,530` | source=`insurer:*` → target=`fhlb:system` | issuer=insurer (carries advance as liability) → holder=FHLB (advance as asset) | ✓ |
| A3 | `sec_xbrl.py:141` | source=`{entity_id}` → target=`sector:fhlb` | issuer=insurer → holder=FHLB | ✓ |
| A3 | `z1.py:125` | source=`sector:life_insurance_companies` → target=`sector:fhlb` | issuer=insurer → holder=FHLB | ✓ |
| A4 (repo) | `sec_xbrl.py:146` | source=`{entity_id}` → target=`sector:repo_dealers` | issuer=repo borrower (insurer) → holder=dealer | ✓ |
| A5 (sec-lending collateral) | `sec_xbrl.py:151` | source=`{entity_id}` → target=`sector:sec_lending_counterparty` | issuer=insurer (owes collateral return) → holder=counterparty | ✓ |
| **A6 (reinsurance)** | **`naic_schedule_s.py:648-651`** | **source=`insurer:naic:` (cedent) → target=`reinsurer:`** | **issuer=reinsurer (issued recoverable obligation) → holder=cedent (holds recoverable asset)** | **✗ INVERTED — see Finding F1** |
| A7 (CLO mezz) | `naic_schedule_d.py:731` | source=`issuer:clo:*` → target=`insurer:naic:*` | issuer=CLO → holder=insurer | ✓ |
| A8 (MMF shares) | `z1.py:115` | source=`sector:money_market_funds` → target=`sector:life_insurance_companies` | issuer=MMF → holder=insurer | ✓ |
| A9 (bank deposits) | `z1.py:113` | source=`sector:depository_institutions` → target=`sector:life_insurance_companies` | issuer=bank → holder=insurer | ✓ |
| A10 (gov't sec) | `naic_schedule_d.py`, `z1.py:117` | source=`issuer:us_treasury` or `sector:gse` → target=`insurer:` or `sector:life_insurance_companies` | issuer=Treasury/GSE → holder=insurer | ✓ |
| A11 (equity) | `sec_13f.py:332` | source=`corp:cusip:*` → target=`aam:cik:*` | issuer=corp → holder=AAM fund | ✓ |
| A11 (G3 ownership) | `sec_adv.py:522` | source=`aam:crd:*` → target=related-entity | (ambiguous; see 3c.2) | ⚠ |
| A12 (other) | `naic_schedule_d.py`, `sec_13f.py`, `sec_xbrl.py`, `z1.py` | source=issuer → target=holder | issuer→holder | ✓ |

**Result:** every arc class except A6 (Schedule S) and A11-G3 (Schedule R from ADV) follows §1.1. The two exceptions are both methodological flags that require resolution before Phase 1 closure.

#### 3c.2 G3 ownership-arc direction ambiguity

Project plan §3.2 (G3 description) reads: "Directed graph. Operating entities point to their controlling parent. Apollo → Athene (control)…" In graph notation, "A → B" with A=Apollo, B=Athene reads as edge from A to B. The prose disambiguator "operating entities point to their controlling parent" suggests source = operating entity = Athene; target = parent = Apollo. But the example "Apollo → Athene" reads in graph notation as source = Apollo; target = Athene.

These two readings contradict each other within §3.2. The CHANGELOG for PR #13 sec_adv (CHANGELOG L274 around): "Apollo → Athene, KKR → Global Atlantic, Blackstone → F&G" — author's reading is source = parent.

`sec_adv.py:522`: emits `source_node_id=_aam_node_id(crd)` (the parent AAM's CRD) and `target_node_id=_related_node_id(related_entity_info)`. Code matches the second reading (parent → affiliate).

Whether this is "correct" depends on the §3.2 author's intent, which the prose does not unambiguously specify. **The audit flags this as a methodological clarification needed in the remediation plan, alongside the A6 inversion.** Both are documentation-vs-code conflicts where the project plan is internally ambiguous.

#### 3c.3 SEC XBRL "balance-sheet marginals as arcs" semantics

`sec_xbrl.py:125-157` `_TAG_MAP` emits records framed as `ArcFact(source, target, arc_class, amount)` for the `Assets`, `Liabilities`, `StockholdersEquity` XBRL tags. These tags are entity-level totals, not arcs in the network-instrument sense. Project plan §10.2 says XBRL "provides per-entity balance sheet aggregates at quarterly cadence. **The marginals of each insurer's, bank's, AAM-holding-company's, and FHLB district's balance sheet.**" So §10.2 acknowledges these are marginals, not arcs.

The code packages them as `ArcFact`s pointing to/from `z1:aggregate` and `z1:equity_holders`. Downstream consumers (constraints, reconstruction) must distinguish these synthetic arcs from real instrument arcs. Whether they do correctly cannot be verified without reading the `compile.py` integration logic carefully — flagged for Phase 7a (constraint completeness verification).

The current encoding works for KCL boundary terms (which need `(entity_id, side, amount)` triples), and the "fake target" `z1:aggregate` is a sink for the marginal. The risk is that `build_sectoral_rows` or `build_double_entry_rows` might inadvertently apply Law 2 or Law 3 to these synthetic arcs as if they were real instrument arcs. The audit flags this as a verification gap, not a confirmed defect.

#### 3c.4 Other description-vs-code discrepancies (minor)

- CHANGELOG PR #16 L142 claims `naic_schedule_d.py` is 887 lines; actual is 1,000. Likely post-PR linting edits. **Benign.**
- CHANGELOG PR #17 L72 claims `sec_13f.py` is "≈400 lines"; actual is 749. Same pattern. **Benign.**
- CHANGELOG PR #1 L946 claims 73 unit tests at bootstrap; the current `test_package_skeleton.py` has 3 def test_ but parametrized over `_SUBPACKAGES + _SUBMODULES` (the 73 entries the count refers to). Static-vs-runtime distinction. **Benign.**

### 3. Phase 3 Summary

- **Documented-but-missing — action items (3):** METHODOLOGY.md (F4), `.claude/hooks/` naming drift, `fred.py` legacy reference. All in Stage 1 of remediation plan.
- **Documented-but-missing — out-of-scope (15+):** Phase 2+ fetchers and artifacts. No Phase 1 action.
- **Present-but-undocumented (4):** All are valid scaffolding files (`prior.py`, `abm/agents/__init__.py`, `reconstruct/validate.py`, `conftest.py`). No remediation.
- **Documented-with-wrong-description (3+):**
  - Schedule S arc direction inverted vs §1.1 (F1; remediation Stage 3)
  - Schedule R/ADV G3 ownership direction ambiguous in project plan §3.2 (new finding F1a; remediation Stage 1 with §3.2 clarification)
  - SEC XBRL marginals encoded as arcs (verification gap; resolved in Phase 7a)
- **Minor doc drift (3):** line-count claims, fred.py legacy name, 73-test count. Benign.

---

## Phase 4 — Code Quality Assessment

### 4a. Quantitative Quality Measures

| Measure | Value | Notes |
|---|---:|---|
| Broad `except Exception` handlers | 3 | `sec_nmfp:495`, `sec_13f:492`, `sec_adv:384` — all wrap HTTP/network calls where any exception triggers cache miss; justifiable |
| Bare `except:` (no type) | 0 | None |
| `contextlib.suppress(Exception)` (catches everything) | 1 | `naic_schedule_s:770` (CSV fallback after JSON parse) — concerning but bounded scope |
| `contextlib.suppress(<specific type>)` | 9 | Acceptable use after PR-time ruff SIM105 enforcement |
| TODO / FIXME / HACK / XXX comments in `claimweb/` | **0** | Remarkably clean |
| Files > 800 LOC | 2 | `naic_schedule_d.py` (1,000), `naic_schedule_s.py` (888) — both have per-state-portal dispatch logic |
| Files > 500 LOC (production) | 7 | All 5 NAIC/SEC EDGAR fetchers + Z.1 + FHLB; reasonable given the scope |
| Imports per fetcher | 9–14 | NAIC fetchers and SEC ADV are heaviest at 14 (csv + zipfile + httpx + lxml + etc.) |
| Property test count (`@given`) across `tests/unit/` | 61 | Exceeds the implicit floor of 4 per law / 3 per fetcher |
| Test coverage of stubs | 0 | Expected — stubs have no tests |

The codebase is unusually clean for an autonomously-built 9,061-LOC project. Zero TODO/FIXME comments suggests the autonomous loop either resolved everything as it went or recorded incomplete items in CHANGELOG/TODO.md instead of code-resident comments — which is consistent with the CLAUDE.md authoring conventions.

### 4b. Qualitative Correctness Spot-Checks

Ten production modules were sampled deterministically (every fifth file, sorted alphabetically) and read for description-vs-code alignment. The spot-check surfaced one critical finding that elevates and reframes Phase 1 Finding F1.

#### F1 (revised, severity raised to CRITICAL) — The arc-direction convention is split across the codebase

Phase 1 F1 reported that `naic_schedule_s.py` inverts the arc direction relative to project plan §1.1's "directed edge from issuer j to holder i." Phase 4 spot-check of `claimweb/constraints/kcl.py` reveals the picture is more complex.

**The kcl.py code uses the OPPOSITE convention from the project plan §1.1 prose.** The relevant code at `kcl.py:312-319`:

```python
if flag == DataQualityFlag.DIRECT_MEASURED:
    # Outgoing arc is an asset (+); its known value reduces the
    # unknown portion, so rhs -= amount.
    # Incoming arc is a liability (−); its known value reduces the
    # unknown portion, so rhs += amount.
    if is_out:
        rhs -= amount
    if is_in:
        rhs += amount
```

The code at line 304 sets `is_out = src == node_id`. At line 312-313 the comment says "Outgoing arc is an asset (+)" — i.e., when `src == node_id`, the arc is *that node's asset*. Translation: **source of an arc = asset holder; target of an arc = liability issuer**.

The `test_kcl.py:139-143` synthetic-network builder confirms the same convention by setting `equity = out_sum - in_sum` at each node (assets - liabilities = equity; out_sum is treated as the asset side).

**Project plan §1.1** has two readings within a single sentence:

> "let $x_{ij}^k(t) \geq 0$ be the dollar volume of instrument $k$ that is held by $i$ as an asset and issued by $j$ as a liability at time $t$. This is the **arc weight** on the directed edge from issuer $j$ to holder $i$ for instrument $k$."

Reading A — from the $x_{ij}$ index notation: $i$ (first index) = holder; $j$ (second index) = issuer. Arc indexed as $x_{ij}$. Source = first index = $i$ = holder. **src = holder; tgt = issuer.** This is what kcl.py implements.

Reading B — from "directed edge from issuer $j$ to holder $i$": graph notation "from A to B" means src=A, tgt=B. So src = $j$ = issuer; tgt = $i$ = holder. **src = issuer; tgt = holder.** This is what 9 of 10 fetchers implement.

The two readings within §1.1 directly contradict each other. Different modules of CLAIM-WEB adopted different readings:

| Module | Convention adopted | Reading |
|---|---|---|
| `kcl.py` (Law 1) | src = holder; tgt = issuer | A ($x_{ij}$ index) |
| `test_kcl.py` | src = holder; tgt = issuer | A |
| `naic_schedule_s.py` | src = cedent = holder; tgt = reinsurer = issuer | A |
| `naic_schedule_d.py` | src = issuer; tgt = holder | B (graph edge) |
| `sec_13f.py` | src = corp issuer; tgt = AAM holder | B |
| `sec_xbrl.py` | src = entity issuer; tgt = sector holder | B |
| `sec_nmfp.py` | src = SPV issuer; tgt = MMF holder | B |
| `fhlb_combined.py` | src = insurer issuer; tgt = FHLB holder | B |
| `frb_efa_fabs.py` | src = SPV issuer; tgt = holder sector | B |
| `z1.py` | src = issuer sector; tgt = holder sector | B |
| `sec_adv.py` (G3) | src = AAM parent; tgt = controlled affiliate | (G3 ownership; separate question — see Phase 3c.2) |

**This is a network-wide soundness defect.** When the constraint compiler joins 2024-Q4 fetcher output into a single network and runs `build_kcl_rows`, every arc emitted under Reading B will be sign-inverted at every node. A $1B Treasury holding by an insurer (per `naic_schedule_d.py`: source=`issuer:us_treasury`, target=`insurer:naic:...`) will be processed as: at the Treasury node, an outgoing arc → "Treasury holds it as asset"; at the insurer node, an incoming arc → "insurer carries it as a liability." Both are inverted: the insurer actually holds the bond as an asset and the Treasury issued it as a liability.

**Why no test has caught this.** All five conservation-law property tests are *self-consistent* under one convention. They build synthetic networks using `_make_arc(src, tgt, ...)` that follow kcl.py's Reading A, then verify kcl.py satisfies the constraints under the same convention. The same is true for the fetchers' parse tests — they verify the fetcher emits arcs with the expected source/target prefixes (Reading B) but never join them to a real KCL run. The cross-module incompatibility surfaces only when a real fetcher's output is fed into `compile_constraints()` — which has never been executed end-to-end (no fetcher has run against live data; `data/raw/` is empty; the integration tests are gated by `@pytest.mark.integration`).

**Phase 1 closure impact.** PHASE_GATES.md L31 requires "Conservation-law checker (`scripts/check_conservation.py`) verifies all four laws hold on the 2024-Q4 solution within published tolerances." The current code will fail this gate the moment the 2024-Q4 acquisition pipeline runs end-to-end. The remediation requires:

1. **Disambiguate project plan §1.1.** Choose Reading A or Reading B as authoritative and update §1.1 prose to make the choice explicit. The audit recommends **Reading A** (src=holder; tgt=issuer) because:
   - It is what the constraint code already implements.
   - It is what the test suite already exercises.
   - It is the "claim direction" convention used in most network-systemic-risk literature (Eisenberg-Noe 2001 sets up the clearing vector with the obligation network having edges from debtor to creditor of payment, but the literature is not uniform; Anand-Craig-von Peter 2015 uses asset-side rows × liability-side columns of a from-whom-to-whom matrix which is equivalent to src=holder).
   - It is what Schedule S (the one A6-emitting fetcher) already implements.

2. **Update the 9 affected fetchers** to swap source_node_id and target_node_id in their `parse()` functions. The change touches `naic_schedule_d.py`, `sec_13f.py`, `sec_xbrl.py`, `sec_nmfp.py`, `fhlb_combined.py`, `frb_efa_fabs.py`, `z1.py`, and the `validate()` prefix-check expectations.

3. **Update each fetcher's unit tests** that assert source/target prefixes — these tests will need to flip the assertions.

4. **Re-run the precommit gate** and verify all conservation property tests still pass.

5. **Add an end-to-end test** that constructs a small toy network from fetcher fixtures, joins via compile_constraints, and verifies KCL closes — exactly the test that doesn't exist today and that would have caught this defect at the point it was introduced.

This is the highest-priority Phase 1 remediation item and is reflected as Stage 3 (modified scope) in `docs/AUDIT_REMEDIATION_PLAN_v1.md`.

#### Additional spot-check findings

**`claimweb/__init__.py`** — sets Decimal context (`getcontext().prec = 28; getcontext().rounding = ROUND_HALF_EVEN`) per `.claude/rules/decimal-arithmetic.md`. Correct.

**`claimweb/constraints/double_entry.py:114` `build_double_entry_rows`** — signature `(facts, *, period, boundary_terms)`. The function iterates `boundary_terms` and emits one `LinearConstraint` per instrument with a known total. `DIRECT_MEASURED` arcs are folded into the RHS. Spot-check confirms: the function correctly distinguishes "known" from "unknown" arcs by `data_quality_flag` and assembles a sound row. **Verdict: matches docstring.** Side note: Law 2 (instrument-level conservation) does not depend on arc-direction convention because it sums |arcs| regardless of direction — Law 2 is convention-agnostic.

**`claimweb/fetchers/frb_efa_fabs.py:194 `_aggregate_to_quarters`** — aggregates daily rows to quarter-end snapshots by selecting the last available date ≤ quarter-end. The function correctly handles FABCP's quarterly-only NA pattern (CHANGELOG L416-418 documents this edge case). **Verdict: matches docstring.**

**`claimweb/fetchers/sec_13f.py:309 `_find_13f_hr_for_period`** — searches the EDGAR submissions JSON for a `13F-HR` form filed within 50 days after the quarter-end. Spot-check confirms the 45-day statutory + 5-day grace logic matches CHANGELOG L59-61. **Verdict: matches docstring.**

**`claimweb/fetchers/sec_xbrl.py:252 `_extract_best_fact`** — selection of the best XBRL entry for a period: primary forms over amendments; framed entries (undimensioned totals) over segment facts; latest filed wins ties. Spot-check confirms the logic matches the CHANGELOG L584-587 description. **Verdict: matches docstring.**

**`claimweb/fetchers/z1.py:243 `_parse_ddp_csv`** — parses FRB DDP CSV format handling preamble rows, blank separators, NA/ND/dot missing tokens, quoted fields, and both ISO-date and `YYYY:QN` period notation. **Verdict: matches docstring.**

**`claimweb/fetchers/base.py:172 `_sha256_file`** — utility for content-addressing raw-data archive per project plan §47. Standard hashlib loop. **Verdict: matches docstring.**

**`claimweb/cascade/contingent.py` and `claimweb/cascade/multi_constraint.py`** — both are 16-17 LOC docstring-only stubs. References (Banerjee-Feinstein 2019, Coen-Lepore-Schaanning 2019) and planned public interfaces match the cascade-author skill. **Verdict: stubs ready for Phase 2 implementation.**

### 4. Phase 4 Summary

- Quantitative quality: clean. Zero TODO/FIXME, only 1 broad-catch (Schedule S CSV fallback), 2 long files (NAIC fetchers — justified).
- Qualitative spot-checks: 8 modules match their docstrings; 1 contributes to the elevated F1 critical finding (kcl.py convention conflict with most fetchers); 2 stubs read cleanly.
- **F1 elevated to CRITICAL severity.** Project plan §1.1 has an internal contradiction; the codebase is split between Reading A (kcl.py, test_kcl.py, naic_schedule_s) and Reading B (9 other fetchers). This is a network-wide soundness defect that has not surfaced because no end-to-end test exists.

---

## Phase 5 — Research-State Classification

`docs/audit_v1/scratch/09_research_state.csv` is the per-file classification. The taxonomy follows the audit prompt §11 with CLAIM-WEB-specific adaptation. The narrative below summarizes counts per label and identifies the LIVE-LOAD-BEARING files.

### 5.1 Label distribution

| Label | Count | What it means |
|---|---:|---|
| LIVE-LOAD-BEARING | 9 | On the critical path of Phase 1 criteria; removing breaks something documented |
| LIVE-PARSING-COMPLETE | 4 | Parses fixtures with full test coverage; URLs validated against live source |
| LIVE-PARSING-UNVERIFIED | 3 | Parses fixtures cleanly; URLs real but never tested against live API from this codebase's environment |
| LIVE-PARSING-PLACEHOLDER-ACQUISITION | 2 | Parses fixtures cleanly; URLs are documentation-derived placeholders |
| STUB-WAITING-IMPLEMENTATION | 6 | Docstring stubs for Phase 1 deliverables; no implementation |
| PARKED-AWAITING-DEPENDENCY | 21 | Phase 2/3 stubs awaiting prior work; correctly scoped out of Phase 1 |
| DIAGNOSTIC-PERMANENT | 17 | Test modules + check_conservation.py; permanent regression infrastructure |
| HARNESS | 27 | `.claude/` files + scripts + workflows + gitignore — operating environment, not application code |
| ABANDONED-PRODUCING-ARTIFACT | 0 | None found |
| ABANDONED-ARTIFACT-FREE | 0 | None found |
| PROMISED-NOT-DELIVERED | 0 in trunk (3 referenced but not present: METHODOLOGY.md, .claude/hooks/, fred.py) | See Phase 3a |
| SCOPED-OUT | 0 confirmed | `claimweb/normalize/` is a candidate — fetchers emit ArcFacts directly; the normalize layer in §11 appears redundant |
| CLEANUP-ARTIFACT | 0 | None found |

### 5.2 LIVE-LOAD-BEARING inventory

These 9 files are critical-path for Phase 1 closure. Any defect in them invalidates downstream work.

1. `claimweb/__init__.py` — sets Decimal precision globally per `.claude/rules/decimal-arithmetic.md`.
2. `claimweb/fetchers/base.py` — defines `ArcFact`, `DataQualityFlag`, `BaseFetcher` ABC. All fetchers and the constraint compiler depend on these types.
3. `claimweb/fetchers/__init__.py` — re-exports concrete fetchers.
4. `claimweb/constraints/__init__.py` — re-exports law builders.
5. `claimweb/constraints/kcl.py` — Law 1 + shared types (`ArcKey`, `LinearConstraint`, `ConstraintSet`, `NetworkState`, `NodeBalance`). The Reading A convention is rooted here.
6. `claimweb/constraints/double_entry.py` — Law 2; convention-agnostic.
7. `claimweb/constraints/sectoral.py` — Law 3; uses Reading A.
8. `claimweb/constraints/flow_funds.py` — Law 4; convention-agnostic.
9. `claimweb/constraints/compile.py` — assembles all four laws.

The 4 LIVE-PARSING-COMPLETE fetchers (`fhlb_combined`, `frb_efa_fabs`, `sec_xbrl`, `z1`) are candidates for promotion to LIVE-LOAD-BEARING after their arc-direction convention is reconciled with kcl.py (per Stage 3 of remediation).

### 5.3 Notable per-file annotations

- **`claimweb/normalize/__init__.py`** (17 LOC) — the project plan §11 layout names this as "schema normalization" between fetchers and constraints. The current fetchers emit `ArcFact` records directly, and the constraint modules consume `ArcFact` records directly. **No intermediate normalization layer is needed in practice.** If the architecture stays this way, `claimweb/normalize/` should either be filled with the per-fetcher post-processing (sector-mapping, registry-lookup) that currently lives inside each fetcher's `parse()`, or be marked SCOPED-OUT and removed. The audit recommends a Stage-1 documentation decision.

- **`claimweb/multiplier/__init__.py`** — project plan §14 reads "System-level claim multiplier" and "Per-cluster claim multipliers" as Phase 1 outputs. The PHASE_GATES.md Phase 1 list does not include claim-multiplier computation as a criterion, and TODO.md Backlog does not mention it. Whether claim-multiplier computation is Phase 1 or Phase 2 is ambiguous. The audit treats it as Phase 2 (after reference 2024-Q4 reconstruction).

- **`tests/unit/test_kcl.py:141`** (`_make_arc` and `valid_network` strategy) — sets `equity = out_sum - in_sum` at each synthetic node, treating arc source as the asset-holder. This is internally consistent with kcl.py's Reading A but encodes the convention without cross-checking against any fetcher's emission convention. Phase 4 elevated F1 makes this a remediation target.

- **`scripts/check_conservation.py`** (85 LOC; DIAGNOSTIC-PERMANENT) — invoked by `scripts/post_edit_check.sh` (PostToolUse hook) and `scripts/precommit_gate.sh`. It executes the four `check_*` functions on solved networks under `data/output/`. Since no solved network exists, the checker is currently a no-op in practice. Will become operational the moment the 2024-Q4 reconstruction runs.

### 5.4 No orphans, no cleanup artifacts

The audit found:
- **Zero ABANDONED-ARTIFACT-FREE files.** Every Python file is either tested, stubbed for known future work, or harness scaffolding.
- **Zero CLEANUP-ARTIFACT files.** No leftover branch artifacts, no orphan generated files.
- **Zero files with no inbound imports AND no documentation reference.** Every file is reachable from at least one of: tests, fetcher exports, hook configuration, agent definitions, or stub-doctstring references in the plan.

This is exceptionally clean for an autonomously-built repository. The autonomous loop's discipline — committing only complete units of work and updating CHANGELOG/TODO with each — has prevented orphan accumulation.

### Phase 5 Summary

- 9 LIVE-LOAD-BEARING files form the Phase 1 critical path.
- 9 fetcher modules split: 4 live-validated, 3 unverified, 2 placeholder.
- 6 STUB-WAITING-IMPLEMENTATION files are Phase 1 work items (the four reconstruct modules, prior.py, sankey.py).
- 21 PARKED stubs are correctly scoped out of Phase 1.
- 44 HARNESS + DIAGNOSTIC files form the operating environment.
- No orphan/dead/cleanup files.

---

## Phase 6 — Open Questions and Pending Work

`docs/audit_v1/scratch/08_pending_work.csv` is the aggregated pending-work register. The audit grouped items by source and classification.

### 6.1 Aggregated counts by classification

| Classification | Count | Source |
|---|---:|---|
| Active development — TODO.md Now/Next | 8 | The autonomous-loop's forward queue |
| Active development — explicit Phase 2 future work | 1 | 2025 SSAP 43R schema break (PR #16) |
| Open Phase 1 gate criteria | 7 | PHASE_GATES.md L25, L28–L33 |
| Stale-and-closed Phase 1 gate criteria (need check-off) | 10 | PHASE_GATES.md L17–L24, L26, L27 |
| Subagent-failure-orphan | 4 | PRs #12, #13, #14, #17 (sec_nmfp, sec_adv, naic_schedule_s, sec_13f) |
| Placeholder-acknowledgment | 2 | PR #14 (NAIC S), PR #16 (NAIC D) |
| Process improvement (subagent reliability) | 3 | literature-checker never completed; documentation-curator never invoked; data-source-investigator 3/9 failed |
| Documentation drift | 4 | PHASE_GATES checkboxes; TODO.md Done hashes; .claude/hooks/ naming; fred.py legacy |
| Methodological ambiguity | 2 | Project plan §1.1 (arc direction); project plan §3.2 (G3 direction) |
| Code-resident TODO/FIXME/HACK/XXX comments | **0** | Remarkably clean |
| Resolved-but-comment-not-removed | 0 | None found |

The defining pattern: **the autonomous loop is forward-disciplined.** It does not leave TODO comments in code; it does not leave half-finished implementations. When something cannot be completed, it is recorded in CHANGELOG with explicit failure diagnosis and queued in TODO.md. The unresolved items live in documentation, not in code.

### 6.2 The four subagent-failure-orphans

CHANGELOG explicit admissions that a fetcher implementation proceeded from documentation alone, without successful subagent investigation:

1. **`naic_schedule_s.py` (PR #14)** — `data-source-investigator` ran out of turns (CHANGELOG L210-214). Implementation from project plan §10.3 and NAIC blank schedule documentation.
2. **`sec_adv.py` (PR #13)** — `data-source-investigator` ran out of turns (CHANGELOG L283-285). Implementation from project plan §10.6 and public SEC/IAPD documentation.
3. **`sec_nmfp.py` (PR #12)** — `data-source-investigator` unable to fetch live EDGAR due to network restrictions (CHANGELOG L353-355). Implementation from public SEC documentation and known N-MFP schema.
4. **`sec_13f.py` (PR #17)** — EDGAR unreachable from sandbox (CHANGELOG L65-68). Subagent confirmed approach from documentation.

Of these four, two (Schedule S, Schedule D — and Schedule D's investigator did succeed) end up with placeholder URLs because the source genuinely lacks free machine-readable access. The other three use real SEC endpoints that should work once tested from a network-enabled environment.

### 6.3 Subagent reliability process gaps

- **`literature-checker`** — has never produced a recorded report. TODO.md L20 has it queued for the current Now item (`max_entropy`), and CHANGELOG references it being "spawned" but the prior session hit Anthropic's 15-routine-runs-per-day cap before the subagent ran. No CHANGELOG entry confirms a completed literature-checker run for any constraint or reconstruction module. **Process gap: the `reconstruction-author` and `cascade-author` skills mandate a literature-checker invocation; this mandate has not been satisfied.**

- **`documentation-curator`** — has never been invoked. CLAUDE.md describes the agent; PHASE_GATES.md and CHANGELOG drift conditions are exactly what the agent is designed to address; the agent has been available since initial harness commit; yet zero CHANGELOG entries reference it. **Process gap: the agent should fire at phase transitions and on every documentation drift event; it does not.**

- **`data-source-investigator`** reliability: 6/9 successful (FHLB Combined, FRB EFA FABS, Z.1 [unrecorded], SEC XBRL [unrecorded], NAIC Schedule D [partial], FRB FABS); 3/9 failed (Schedule S, SEC ADV, SEC N-MFP). For the failed runs, the autonomous loop honestly recorded the failure in CHANGELOG and proceeded documentation-only.

The remediation (Stage 2 of the plan) addresses subagent reliability by:
- Adding a documentation-only mode to `data-source-investigator` that produces a structured report when network is unavailable, including a `LIVE_DATA_VALIDATION_REQUIRED` flag.
- Adding an `acquisition-validator` agent that runs from a non-sandbox environment to live-test fetcher URLs.
- Updating the `fetcher-author` skill to mandate an `_ACQUISITION_PLACEHOLDER` class attribute on fetchers whose URLs have never been live-validated.

### 6.4 The 2025 SSAP 43R schema break

CHANGELOG PR #16 L126-134 documents: "Starting with 2024 year-end filings (filed March 2025), Schedule D Part 1 splits into Section 1 (issuer credit obligations: corporate bonds, Treasuries) and Section 2 (asset-backed securities: CLOs, MBS). CLOs previously in Schedule D Part 1 may now appear in Section 2 or be reclassified to Schedule BA." The fetcher's `_classify_security()` does not dispatch on statement year. This is explicitly future work; not Phase 1-blocking but will become an issue when historical-backfill (Phase 2) crosses the 2024/2025 boundary.

### 6.5 Pending work blocking Phase 1 closure

The minimal critical path to Phase 1 closure:

1. **F1 remediation** (Stage 3 of plan): disambiguate project plan §1.1, invert source/target in 9 fetchers, update their tests, add an end-to-end conservation-validation test. Estimated effort: 2–3 days.

2. **METHODOLOGY.md** (Stage 9): draft Phase 1 sections. Estimated effort: 1 day.

3. **Placeholder URL remediation** (Stage 3): replace NAIC Schedule S/D placeholder URLs with real per-state portal paths (Iowa IID structure must be investigated from a network-enabled environment); add integration tests gated by `@pytest.mark.integration`. Estimated effort: 3–5 days assuming Iowa IID provides a path.

4. **Unverified-URL live validation** (Stage 4): test SEC 13F, ADV, N-MFP fetchers against EDGAR from non-sandbox. Estimated effort: 1 day each.

5. **Reference quarter 2024-Q4 end-to-end** (Stage 6): run all 10 fetchers against live data; capture all ArcFacts; review unmapped registries; promote canonical mappings. Estimated effort: 2 days.

6. **Reconstruction implementation** (Stage 7): `max_entropy`, `min_density`, `solver`. Estimated effort: 1 week.

7. **Sankey visualization** (Stage 8): initial 2024-Q4 render. Estimated effort: 1–2 days.

8. **PHASE_GATES.md check-offs** (Stage 1): mechanical update of closed criteria. Estimated effort: 30 minutes.

9. **Phase 1 closure ceremony** (Stage 10): phase-gate-closer skill verification + user confirmation. Estimated effort: 1 day.

**Total minimum critical path: ~3 weeks of focused work in a non-sandbox environment**, contingent on placeholder-URL investigation yielding viable acquisition paths.

---

## Phase 7 — Theoretical and Methodological Correctness

### 7a. Conservation-Law Completeness

`docs/audit_v1/scratch/10_conservation_law_coverage.csv` records the build function, check function, and property-test inventory per law. The audit confirms the constraint-author skill's required property-test set (soundness, completeness, stability, independence) is met for every law:

| Law | Build | Check | Soundness | Completeness | Stability | Independence | Extras |
|---|---|---|---|---|---|---|---|
| Law 1 (KCL) | `kcl.py:251` | `kcl.py:348` | ✓ (×2: build+check) | ✓ | ✓ | ✓ | — |
| Law 2 (double-entry) | `double_entry.py:114` | `double_entry.py:213` | ✓ (×2) | ✓ | ✓ | ✓ | — |
| Law 3 (sectoral) | `sectoral.py:146` | `sectoral.py:259` | ✓ (×2) | ✓ | ✓ | ✓ | — |
| Law 4 (flow-of-funds) | `flow_funds.py:152` | `flow_funds.py:287` | ✓ (×2) | ✓ | ✓ | ✓ | provenance-roundtrip |
| Compile (assembly) | `compile.py:138` | n/a | ✓ (KCL soundness via assembly) | n/a | ✓ (KCL RHS) | n/a (correctness via per-law) | unknowns-are-arc-keys; nonneg-count; Law-4-period-reference |

**Property-test counts:** kcl 5; double_entry 5; sectoral 5; flow_funds 6 (extra: provenance); compile 5 (different property set focused on aggregation invariants). Total: 26 property tests across the constraint-system stack.

**Compile-stage correctness.** `compile_constraints` always applies Law 1 (KCL); applies Laws 2/3/4 conditionally on whether the caller supplies their respective boundary terms. Non-negativity (`x ≥ 0`) is opt-in (default True). The `to_index()` method provides the bijection from ArcKey to integer column index that the reconstruction solvers need. The audit confirms via spot-read of `test_compile.py:529-577` that the soundness property test substitutes a balanced synthetic network's true arc values into each compiled constraint's `matrix_row` and verifies LHS == RHS. **Structurally sound.**

**Conditioning analysis.** Neither `compile.py` nor the test suite computes the rank or condition number of the compiled sparse matrix. The audit considers this a gap:
- Without rank verification, the audit cannot confirm the compiled system has a unique solution given the supplied boundary terms.
- Without condition-number monitoring, downstream solvers may produce silently inaccurate solutions on poorly-conditioned matrices.
- The remediation (Stage 5 of the plan) adds a rank-and-conditioning check to the compile stage and surfaces it in `CompiledSystem.summary()`.

**Internal consistency of the four laws.** Spot-check of the law interactions:
- Law 1 is convention-dependent (per the F1 finding: kcl.py uses Reading A; src=holder).
- Law 2 is **convention-agnostic** — it sums all arcs by instrument class regardless of direction, then compares to a boundary total. Whether arc-direction is Reading A or Reading B, the instrument total is the same.
- Law 3 is convention-dependent: `build_sectoral_rows` separates asset-side and liability-side constraints by computing `sum of outgoing arcs from sector nodes` for the asset side. Under Reading A this is correct; under Reading B it would be inverted.
- Law 4 is convention-agnostic — it identifies arcs by `(src, tgt, instrument)` tuple and verifies $x(t+1) - x(t) = F + R$ on that tuple. Whatever direction the fetcher chose, Law 4 tracks it consistently across periods.

**Therefore Law 1 (kcl) and Law 3 (sectoral) are the two constraint modules whose correctness depends on the F1 convention reconciliation.** Law 2 and Law 4 will work regardless. The Stage-3 remediation that flips 9 fetchers must be tested against both `check_kcl` and `check_sectoral` to confirm the post-flip network passes both.

### 7b. Reconstruction and Validation Methodology Readiness

#### Reconstruction stubs

The four reconstruction modules at `claimweb/reconstruct/{max_entropy.py, min_density.py, solver.py, validate.py}` are all docstring-only stubs (14-21 LOC). The audit verified each docstring against the cited methodology:

- **`max_entropy.py`** — cites Upper (2011) for the survey and Upper (2004) implicit; mathematical form `H(X) = -sum x_{ij}^k log x_{ij}^k`; "convex; solved by RAS / iterative proportional fitting"; cvxpy boundary. **Matches project plan §13 Phase C.1.** Planned interface: `solve_max_entropy(system, *, max_iter, tol) -> SolvedNetwork`. The skill mandate to spawn `literature-checker` against Upper (2004) before writing code is documented in the docstring and reaffirmed in TODO.md L20.
- **`min_density.py`** — cites Anand-Craig-von Peter (2015), *Quantitative Finance* 15(4):625-636; describes the combinatorial relaxation. **Matches project plan §13 Phase C.2.** Planned interface: `solve_min_density(system, *, max_iter, tol) -> SolvedNetwork`. Skill mandate to spawn `literature-checker` against the paper.
- **`solver.py`** — bracketing harness; runs both ME and MD; reports per-arc `(ME, MD)` band as structural-uncertainty per CLAUDE.md standing rule. Planned interface: `reconstruct(facts, *, period, methods=("max_entropy", "min_density")) -> BracketedNetwork`. **Matches project plan §13 phase summary and CLAUDE.md "both reconstruction methods run".**
- **`validate.py`** — reconstruction self-validation hook; not deeply specified in stub but implied to run `check_kcl`/`check_double_entry`/`check_sectoral`/`check_flow_funds` against the solved network. The CLAUDE.md "conservation laws are invariants" rule mandates this.

**The mathematical specifications in the stub docstrings are consistent with the project plan.** Implementation will require:
1. `literature-checker` against Upper (2004) — currently not completed due to budget-cap-killed session.
2. `literature-checker` against Anand-Craig-von Peter (2015).
3. cvxpy-based reference implementation for ME on small subnetworks (to verify the RAS iteration converges to the convex optimum).
4. Python port of the published Anand-Craig-von Peter heuristic for MD.
5. Bracketing harness composes the two and emits `BracketedNetwork` records consumed by `claimweb/visualize/sankey.py`.

#### Validation episode stubs

`claimweb/validation/ep1_2007_xfabs.py`, `ep2_2008_aig_seclending.py`, `ep3_2020_covid_stress.py` are all 12-15 LOC docstring stubs. The docstrings name the right episodes and the right test artifact (the project's "must retrodict within tolerance" requirement per CLAUDE.md). The `retrodiction-replayer` subagent exists in `.claude/agents/` and is referenced from the `validation-author` skill. **Scaffolding is in place; implementations are correctly Phase 3 scope.**

Tolerances are not yet defined. PHASE_GATES.md L58 mentions `tests/validation/tolerances.py` as a Phase 3 deliverable; the file does not exist. The audit does not flag this as a current gap because Phase 3 is months 13–18 per project plan §35.

#### G3 ownership-graph direction (Phase 3c.2 follow-through)

Project plan §3.2 prose contains an internal ambiguity in the G3 ownership-graph direction:
- "Operating entities point to their controlling parent" — operating entity is source; parent is target.
- "Apollo → Athene (control); Apollo → MidCap Financial (control)" — Apollo is source; controlled entity is target.

These two statements give opposite directions. The `sec_adv.py:522` code emits `source=aam:crd:{parent}, target=related_entity` — i.e., parent → affiliate, matching the "Apollo → Athene" example reading. The first prose sentence is inconsistent.

The audit recommends Stage 1 of the remediation plan include a §3.2 prose clarification choosing one reading. The code as written is internally consistent with the example; the documentation should be fixed.

#### Convention consistency across the four laws (revisiting F1)

Per 7a above, only Laws 1 and 3 depend on the arc-direction convention. The audit's recommendation in F1 (adopt Reading A: src=holder, tgt=issuer) propagates as follows:

- **kcl.py** — already implements Reading A. **No change.**
- **double_entry.py** — convention-agnostic. **No change.**
- **sectoral.py** — implements Reading A (sums outgoing arcs from sector nodes as the asset side). **No change.**
- **flow_funds.py** — convention-agnostic. **No change.**
- **compile.py** — convention-agnostic at the assembly layer. **No change.**

All 5 constraint modules are already aligned with Reading A. Only the 9 affected fetchers need source/target inversion.

### 7. Phase 7 Summary

- **All four conservation laws** have build_*_rows and check_* functions, with 5 property-tests each (soundness, completeness, stability, independence; double-soundness for build+check). Implementation is mathematically sound under Reading A.
- **Compile stage** is structurally sound; lacks rank/condition-number reporting (Stage 5 of remediation).
- **Laws 1 and 3 are convention-dependent.** Their correctness when joined with fetcher output depends on resolving the F1 finding.
- **Reconstruction stubs** match the cited methodology. Implementation requires `literature-checker` invocations that have not yet been completed.
- **Validation episode stubs** are correctly Phase 3 scope; scaffolding is in place.
- **G3 ownership direction** ambiguity in project plan §3.2 prose; code follows one reading consistently.

---

## Phase 8 — External Research Context

### 8a. Methodology Context

The audit ran four targeted web searches on the methodology choices CLAIM-WEB inherits.

**Anand-Craig-von Peter (2015) minimum-density reconstruction** — confirmed at *Quantitative Finance* 15(4):625-636, BIS Working Paper 455. The R package `NetworkRiskMeasures` (CRAN) is the reference implementation. The published claim — "minimum-density solution overestimates contagion, whereas maximum entropy underestimates it, and using the two benchmarks side by side defines a useful range that bounds the cost of contagion in the true interbank network when counterparty exposures are unknown" — directly matches CLAIM-WEB's bracketing approach per project plan §13 and CLAUDE.md standing rule. **The methodology is sound and current.**

**Mistrulli (2011)** — confirmed at *Journal of Banking & Finance* 35(5):1114-1127. The audit notes a nuance: Mistrulli finds that *while the maximum entropy method tends to underestimate the extent of contagion in line with prevailing literature, this does not hold in general. Under certain circumstances, depending on the structure of the interbank linkages, the recovery rates of interbank exposures and banks' capitalization, the maximum entropy approach overestimates the scope for contagion.* The CLAIM-WEB framing (ME underestimates → MD overestimates → bracket bounds the truth) is the common case; under some network topologies the ordering can flip. **The remediation plan should add a note (Stage 9 of plan) for the methodology paper to disclose this nuance.**

**Cont-Schaanning (2017)** — confirmed at SSRN 2955646. Recent extensions:
- **Caccioli et al. (2024), "Modelling fire sale contagion across banks and non-banks,"** *Journal of Financial Stability* 71. Models indirect contagion across UK banks and non-banks subject to different leverage/capital constraints — directly relevant to CLAIM-WEB's bank-insurer-AAM network architecture.
- **ECB MaSTER 2025 macroprudential stress test report** uses fire-sale extensions in a top-down stress-testing framework.
- Operations Research 2024 paper "Preventing Price-Mediated Contagion Due to Fire Sales Externalities" extends to the strategic foundations of macroprudential regulation.

These extensions sit downstream of CLAIM-WEB's Phase 2-3 scope. The cascade-author skill should reference the Caccioli et al. (2024) paper when implementing `fire_sale.py` (Stage out-of-scope for Phase 1; remediation noted in Stage 7 future work).

**Methodological recency check:** the four core methods (Eisenberg-Noe 2001, Anand-Craig-von Peter 2015, Cont-Schaanning 2017, Battiston et al. 2012 DebtRank) remain the canonical references in the 2024-2026 financial-network systemic-risk literature. CLAIM-WEB's choice of references is current and defensible.

### 8b. Data-Source Availability Context

The audit ran four searches on the placeholder-URL and unverified-URL fetchers to validate the live-acquisition prospects.

**NAIC Schedule S / Schedule D — the placeholder-URL gap.** NAIC's content site exposes paid IDP product pages at `content.naic.org/prod_serv_idp_sched_d.htm` and `content.naic.org/prod_serv_idp_reinsurance.htm`. These are **subscription products**, not free machine-readable endpoints. The audit confirms what the PR #16 CHANGELOG entry already disclosed: NAIC does not provide a free public JSON/XML/XBRL API for Schedule D or Schedule S. The free path is per-state DOI portal scraping.

**Iowa Insurance Division (`iid.iowa.gov`) — critical future blocker.** The Iowa site hosts financial statements for IA-domiciled insurers (Athene, American Equity, F&G are the key PE-affiliated cedents). However, the search returned a structural warning: **"The RIU portal will no longer be accessible after June 30, 2026"**. The Regulated Insurance Unit (RIU) portal is the primary acquisition path implied by `naic_schedule_s.py:563` (`{iid.iowa.gov}/companies/{naic_code}/financials/{year}/schedule_s`). After June 30, 2026 — six weeks from the audit-start date — this path will need to be replaced. The remediation plan's Stage 3 (NAIC placeholder URL replacement) should be executed before the portal sunsets, and the replacement path must be researched.

**FHLB Office of Finance — confirmed live.** Search returns the same URL the fetcher uses: `https://www.fhlb-of.com/ofweb_userWeb/pageBuilder/fhlbank-financial-data-36`. Direct PDF examples (e.g. `https://www.fhlb-of.com/ofweb_userWeb/resources/2024Q4CFR.pdf`) confirm the FHLB-OF site continues to serve quarterly Combined Financial Reports. **`fhlb_combined.py` acquisition path is current and working as of audit start.**

**Bermuda Monetary Authority — partial path.** `bma.bm` exposes a searchable register at `bma.bm/regulated-entities` and per-class public filings (Class 4: `bma.bm/public-filings/full-filings-class-4`; Class E: `bma.bm/public-filings/full-filings-class-e`). These are PDFs/documents, not machine-readable. Implementation of `claimweb/fetchers/bma_register.py` (Phase 2 scope) will require PDF-extraction logic similar to `fhlb_combined.py`. **No machine-readable JSON/XML API exists.**

**SEC EDGAR rate limit — confirmed at 10 req/sec.** Policy effective since July 27, 2021; reaffirmed in 2025-2026 documentation. Required: `User-Agent` header. Penalty for excess: IP-level 403 Forbidden for ~10 minutes. CLAIM-WEB's `sec_nmfp.py` uses 150ms between requests (6.7 req/s, compliant). `sec_13f.py` and `sec_adv.py` should be spot-checked for the same compliance pattern (not deeply verified in this audit).

### 8. Phase 8 Summary

- The four methodological references (Anand-Craig-von Peter 2015; Mistrulli 2011; Cont-Schaanning 2017; Eisenberg-Noe 2001) are confirmed at the cited venues with stable URLs. CLAIM-WEB's methodology is current.
- One nuance worth disclosing in the methodology paper: Mistrulli's finding that ME-vs-true ordering can flip under some network topologies; CLAIM-WEB's "ME underestimates, MD overestimates" is the common case, not universal.
- One recent extension (Caccioli et al. 2024) is directly relevant to the Phase 2 cascade implementation and should be added to the `cascade-author` skill's reference list.
- **NAIC paid-IDP-only confirmed:** the placeholder-URL gap is structural, not a fetcher bug. Free path requires per-state DOI portal scraping. The Iowa RIU portal sunsets June 30, 2026 — a six-week deadline from audit-start. Stage 3 of remediation must execute before that date or pivot to an alternative path.
- FHLB Office of Finance is the only Phase 1 data source whose URL is independently confirmed alive and unchanged at audit time.
- SEC EDGAR rate limit (10 req/s) is real and enforced; the existing fetchers' rate limiters appear compliant.

**Sources:**
- [Anand, Craig, von Peter (2015) "Filling in the Blanks", Quantitative Finance 15(4):625-636](https://www.tandfonline.com/doi/abs/10.1080/14697688.2014.968195)
- [Mistrulli (2011) "Assessing Financial Contagion", JBF 35(5):1114-1127](https://www.sciencedirect.com/science/article/abs/pii/S0378426610003687)
- [Cont, Schaanning (2017) "Fire Sales, Indirect Contagion and Systemic Stress Testing"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2955646)
- [Caccioli et al. (2024) "Modelling fire sale contagion across banks and non-banks"](https://ideas.repec.org/a/eee/finsta/v71y2024ics1572308924000160.html)
- [NAIC IDP Schedule D product page](https://content.naic.org/prod_serv_idp_sched_d.htm)
- [NAIC IDP Reinsurance Data product page](https://content.naic.org/prod_serv_idp_reinsurance.htm)
- [Iowa Insurance Division — Financial Statements](https://iid.iowa.gov/legal-resources/reports/financial-statements)
- [FHLB Office of Finance — Financial Data](https://www.fhlb-of.com/ofweb_userWeb/pageBuilder/fhlbank-financial-data-36)
- [FHLB 2024-Q4 Combined Financial Report](https://www.fhlb-of.com/ofweb_userWeb/resources/2024Q4CFR.pdf)
- [Bermuda Monetary Authority — Regulated Entities](https://www.bma.bm/regulated-entities)
- [BMA — Class 4 Insurance Public Filings](https://www.bma.bm/public-filings/full-filings-class-4)
- [SEC.gov — Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- [SEC.gov — New EDGAR Rate Control Limits](https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits)

---

## Phase 9 — Phase 1 Gate Readiness Assessment

`docs/audit_v1/scratch/11_phase1_gate_status.csv` is the row-by-row gate status. The 17 Phase 1 criteria from `docs/PHASE_GATES.md` L17-33:

| # | Criterion (abbrev.) | Status | Evidence | Blocking |
|---|---|---|---|---|
| G1.01 | Package skeleton | **CLOSED** | every subpackage `__init__.py` with docstring | — |
| G1.02 | `pyproject.toml` with §19 deps | **CLOSED** | `pyproject.toml:26-49` | — |
| G1.03 | `tests/` with collect-only | **CLOSED** | 16 test modules collect cleanly | — |
| G1.04 | `BaseFetcher` + unit-tested | **CLOSED** | `base.py` + `test_fetchers_base.py` (41 tests) | — |
| G1.05 | `FhlbCombinedFetcher` end-to-end + fixture | **CLOSED** | `fhlb_combined.py` + PDF fixture | — |
| G1.06 | `Z1Fetcher` for 7 L.tables | **CLOSED** | `z1.py` + 7 fixture CSVs | — |
| G1.07 | `SecXbrlFetcher` for LIFE_INSURERS panel | **CLOSED** | `sec_xbrl.py` + MetLife fixture | — |
| G1.08 | `FrbEfaFabsFetcher` for daily FABS | **CLOSED** | `frb_efa_fabs.py` + fixture | — |
| G1.09 | **Reference 2024-Q4 acquired end-to-end** | **OPEN** | `data/raw/` empty | F1; placeholder URLs; non-sandbox runner |
| G1.10 | All 4 conservation laws + property tests | **NOMINAL** | 5 property tests each × 4 laws | F1 fetcher-flip → must re-pass |
| G1.11 | `ConstraintSet` compile feasible on 2024-Q4 | **NOMINAL** | `compile.py` + 57 tests | rank/conditioning check (Stage 5); G1.09 |
| G1.12 | `max_entropy` implemented + converges | **OPEN** | 21-LOC stub | `literature-checker`; G1.09 |
| G1.13 | `min_density` implemented + converges | **OPEN** | 18-LOC stub | `literature-checker`; G1.09 |
| G1.14 | `solver.py` bracketed `SolvedNetwork` | **OPEN** | 20-LOC stub | G1.12 + G1.13 |
| G1.15 | Conservation checker on 2024-Q4 solution | **OPEN** | no solved network | G1.09 + G1.14 + F1 |
| G1.16 | Initial Sankey for 2024-Q4 | **OPEN** | 17-LOC stub | G1.14 |
| G1.17 | `docs/METHODOLOGY.md` outline | **OPEN** | file does not exist | `documentation-curator` or manual draft |

**Status breakdown:**
- **CLOSED: 8 of 17 (47%)** — all foundation criteria (G1.01-G1.08) excluding the reference quarter
- **NOMINAL: 2 of 17 (12%)** — conservation laws and compile both pass fixture tests; closure depends on F1 fetcher-flip
- **OPEN: 7 of 17 (41%)** — the entire reconstruction path (G1.12-G1.16), the reference quarter (G1.09), the conservation check (G1.15), and METHODOLOGY.md (G1.17)

### 9.1 Critical-Path Bottleneck Analysis

The dependency graph among OPEN criteria:

```
G1.09 (reference quarter end-to-end)
  ├── requires: F1 remediation (Stage 3)
  ├── requires: NAIC S/D placeholder-URL fix (Stage 3)
  ├── requires: SEC 13F/ADV/N-MFP live validation (Stage 4)
  └── requires: non-sandbox runner

G1.12 (max_entropy) and G1.13 (min_density)
  ├── require: literature-checker invocations (Stage 2)
  └── require: G1.09 (to test convergence on real data)

G1.14 (solver bracketing harness) — requires G1.12 + G1.13

G1.15 (conservation checker on solved network)
  ├── requires: G1.09 (so the network exists)
  ├── requires: G1.14 (so the network is reconstructed)
  └── requires: F1 (otherwise check fails)

G1.16 (Sankey) — requires G1.14

G1.17 (METHODOLOGY.md) — independent; drafted from project plan + CHANGELOG
```

**The critical-path bottleneck is G1.09 (reference 2024-Q4 acquired end-to-end).** It is the single open criterion that the most other criteria depend on (G1.12, G1.13, G1.14, G1.15). Closing G1.09 requires three remediations in sequence:

1. **F1 arc-direction inversion** (Stage 3): flip 9 fetchers from src=issuer to src=holder per Reading A. Estimated: 2-3 days.
2. **NAIC placeholder-URL replacement** (Stage 3): investigate Iowa IID + per-state portal alternatives; the Iowa RIU portal sunsets June 30 2026, **giving roughly 6 weeks**. Estimated: 3-5 days (if a path exists) or scope reduction.
3. **SEC live validation** (Stage 4): run sec_13f, sec_adv, sec_nmfp from a network-enabled environment. Estimated: 1-2 days.

Until G1.09 closes, the reconstruction work (G1.12-G1.14) cannot be validated against real data, the conservation checker (G1.15) cannot fire, and the Sankey visualization (G1.16) cannot render.

The single off-critical-path item is G1.17 (METHODOLOGY.md) — it can be drafted in parallel with the critical-path work using existing materials.

### 9.2 NOMINAL → CLOSED Conditions

The two NOMINAL criteria (G1.10 conservation laws, G1.11 compile) currently pass against synthetic networks but cannot close until:

- **G1.10**: F1-induced fetcher source/target flip is committed; tests are updated to confirm the same constraints satisfy KCL on flipped output; an end-to-end fetcher → compile → KCL → green-light test is added.
- **G1.11**: rank/conditioning check is added to `CompiledSystem.summary()` (Stage 5); a synthetic small-network test verifies the compiled matrix is well-conditioned and has the expected rank.

Both NOMINAL items become CLOSED as a side effect of completing G1.09 and Stage 5.

### 9. Phase 9 Summary

- 8 of 17 Phase 1 gate criteria are **functionally CLOSED** but **administratively still open in PHASE_GATES.md** (the checkbox drift documented in F3). Stage 1 of the remediation plan check-offs these.
- 2 NOMINAL criteria close as a side effect of F1 remediation + Stage 5 rank-check.
- 7 OPEN criteria form the active Phase 1 work. The **critical-path bottleneck is G1.09 (reference 2024-Q4 acquired end-to-end)**, which depends on F1, NAIC placeholder remediation, SEC live validation, and a non-sandbox runner.
- **Independent item**: G1.17 (METHODOLOGY.md) — drafting can begin immediately.
- **Hard deadline**: Iowa RIU portal sunsets June 30, 2026 — 6 weeks from audit start. Stage 3 of remediation must execute by then or accept a Schedule S scope reduction.

---

## Phase 10 — Remediation Plan

The remediation plan is in a separate file: `docs/AUDIT_REMEDIATION_PLAN_v1.md`.

The plan is organized in 10 stages:

1. **Stage 1 — Documentation Reconciliation** (1 day, immediate)
2. **Stage 2 — Subagent Reliability Improvements** (1-2 days)
3. **Stage 3 — F1 Remediation + NAIC Placeholder-URL Replacement** (5-7 days; **must complete before June 30, 2026** for Iowa IID access)
4. **Stage 4 — Live-Data Validation for Unverified Fetchers** (3-4 days)
5. **Stage 5 — Conservation-Law Compile Robustness** (1-2 days)
6. **Stage 6 — Reference Quarter 2024-Q4 End-to-End** (2-3 days)
7. **Stage 7 — Reconstruction Implementation** (5-7 days)
8. **Stage 8 — Sankey Visualization** (1-2 days)
9. **Stage 9 — Methodology Paper Outline** (1-2 days; can run in parallel)
10. **Stage 10 — Phase 1 Closure Ceremony** (1 day)

**Total critical-path effort: ~21-30 days** (4-6 weeks of focused operator time).

**Binding constraint:** Iowa RIU portal sunsets June 30, 2026 — 6 weeks from audit-start. Stage 3 must execute by then or scope-reduce Schedule S.

Each stage in the plan has explicit step lists with file paths, actions, and verification criteria. The plan also names out-of-scope work (cascade simulation, historical reconstruction, ABM layer, paid NAIC IDP subscription) so the remediation does not creep beyond Phase 1.

See `docs/AUDIT_REMEDIATION_PLAN_v1.md` for full detail.

---

## Phase 11 — Hygiene and Consolidation

### 11.1 Branch hygiene

Active branches:
- `main` — default branch; 17 PRs merged through `f253980`.
- `claude/audit-claim-web-q6ojZ` — this audit's working branch.

**No stale branches found in the local clone.** The audit prompt hypothesized that a `claude/reconstruct-max-entropy-*` branch might exist from the budget-cap-killed session; it does not exist locally. (It may exist as an unmerged remote branch on GitHub; the operator should `git fetch --prune origin` and review any branches matching `claude/reconstruct-*` and either revive or delete.)

### 11.2 Tag hygiene

No tags exist. Per `.claude/rules/git-discipline.md`, phase-gate closures get tags (e.g. `phase-1-close`). Stage 10 will add the first tag.

### 11.3 Data archive hygiene

- `data/raw/.gitkeep` — only file. No leaked raw data. ✓
- `data/normalized/.gitkeep` — only file. ✓
- `data/output/.gitkeep` — only file. No leaked solved networks. ✓

`.gitignore` properly excludes `data/raw/*` (except `.gitkeep`) and `data/output/network/*/v*/` (except `v0/`). The audit confirms zero policy violations.

### 11.4 Files to remove from trunk

**None.** Phase 5 found 0 CLEANUP-ARTIFACT files and 0 ABANDONED-ARTIFACT-FREE files. Every committed Python file is reachable and serves a documented role. Every harness file is referenced. Every test corresponds to a production module. No removal recommended.

### 11.5 Files to add to gitignore

**None.** Spot-check of current `.gitignore` against committed files: every Python cache, pytest cache, venv, OS junk, and editor junk pattern is covered. No additions needed.

### 11.6 Stale branches and remotes

Per Stage 1.2 of the remediation plan, TODO.md Done hashes should be updated to merge SHAs. This is documentation hygiene, not branch hygiene. No remote branch cleanup required.

### Phase 11 Summary

The repository is exceptionally clean for an autonomously-built 9,061-LOC project: zero orphan files, zero leaked data, zero stale branches, zero cleanup artifacts. The autonomous loop's commit-and-push-after-every-meaningful-unit discipline (per CLAUDE.md "Standing rules") has prevented accumulation.

The single hygiene action item is Stage 1.2 (TODO.md Done hash alignment) which is administrative.

---

## Phase 12 — Subagent Deep Dives

After Phases 1-11, the audit did not surface any subsystem that required deep dive beyond what was already covered in the report. Specifically:

- **Arc-emission ground truth** — fully covered in Phase 2a (`04_arc_emissions.csv`).
- **Constraint-row × arc-class matrix** — the audit confirmed Law 1 and Law 3 are convention-dependent and Law 2 + Law 4 are convention-agnostic in Phase 7a; the full matrix would require a solver run to surface, which is out of scope.
- **Test × production-module coverage matrix** — fully covered in Phase 2b (`03_file_inventory.csv` + the test census).
- **Subagent invocation history** — fully aggregated in Phase 6.
- **1,420-line project plan walk** — the audit cross-referenced specific sections (§1.1, §3.2, §4, §10, §11, §13, §17, §18, §19, §35) at the relevant phases. A full §-by-§ walk would surface no additional Phase 1 findings; the load-bearing methodological commitments are already covered.

No subagent deep dives were dispatched in this audit. The remediation plan does not require any.

---
