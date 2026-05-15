# CHANGELOG — CLAIM-WEB

Lab-notebook style. Append entries; don't rewrite history. Both successes and failed approaches go here. The "Failed approaches" section is as important as the "Completed" section — without it, successive sessions re-attempt the same dead ends.

## Convention

Each entry begins with a date and short title. Use these section markers within an entry:
- **What:** what was done
- **Why:** why it was done now (which phase / gate)
- **Result:** what came out (with file paths to artifacts)
- **Failed:** what was tried and didn't work, with brief diagnosis
- **Next:** what this unlocks or what comes next

After each meaningful unit of work, append an entry, commit, and push.

## Current status

- **Phase:** Foundation (Phase 1 of 5 per project plan §35)
- **Reference period:** target 2024-Q4 for end-to-end reconstruction
- **First arc target:** FHLB advances → U.S. life insurer members (per project plan first-week actions)
- **Methodology version:** v0 (pre-publication, freely revisable)

## Entries

<!-- Append entries here. Newest first. Example below — delete after first real entry. -->

### 2026-05-15 — constraints: balance-sheet identity Law 1 (project plan §1.1)

- **What:** Implemented `claimweb/constraints/kcl.py` — the Law 1
  (balance-sheet identity / node-level KCL) constraint module.  Created:
  - Shared constraint types: `ArcKey`, `LinearConstraint`, `ConstraintSet`
    (to be imported by future constraint modules and `compile.py`).
  - KCL-specific types: `NodeBalance`, `NetworkState`, `KCLViolation`,
    `KCLResult`.
  - `build_kcl_rows(network: NetworkState) -> ConstraintSet` — compiles one
    sparse linear equality per node for the period.  `DIRECT_MEASURED` arcs
    are folded into the RHS as constants; all other arcs remain as ±1
    variables.  Duplicate arcs (same source/target/instrument/period) are
    aggregated; the highest-quality `DataQualityFlag` wins.
  - `check_kcl(network: NetworkState, *, tol: Decimal) -> KCLResult` — directly
    verifies Law 1 on a solved/concrete network.  Tolerance is relative
    (default 0.01 % of total assets) with a 0.01 M absolute floor, per the
    conservation-laws standing rule.
  - Helper `_provenance_node` for extracting the node ID from a provenance
    string (used in tests and the independence property check).
  Created `tests/unit/test_kcl.py` with 35 tests (5 property-based +
  30 unit):
  - `test_soundness_build_kcl_rows` — hypothesis: on a Law-1-satisfying
    network, all constraints are satisfied when arc values are substituted.
  - `test_soundness_check_kcl` — hypothesis: check_kcl returns satisfied=True
    on a Law-1-satisfying network.
  - `test_completeness_check_kcl` — hypothesis: perturbing one arc by ≥ 1 000
    causes at least one violation to be detected.
  - `test_stability_build_kcl_rows` — hypothesis: changing a DIRECT_MEASURED
    arc by δ shifts the source node's RHS by −δ and the target node's RHS by
    +δ; all other nodes' RHS are unchanged.
  - `test_independence_build_kcl_rows` — hypothesis: each constraint's
    matrix_row references only arcs incident to that constraint's node.
  - `TestBuildKclRows` — 11 unit tests covering empty networks, single arcs,
    direct-measured folding, nonfinancial assets, multiple instruments, and
    duplicate arc aggregation.
  - `TestCheckKcl` — 13 unit tests covering satisfied/violated detection,
    tolerance floor, diagnostic fields, ghost nodes, and duplicate arcs.
  - `TestProvenanceNode`, `TestBuildCheckRoundTrip` — 6 additional tests.
  Also: installed `hypothesis` and its dependencies into the `uv`-managed
  pytest tool environment (was missing; gate was failing with
  `ModuleNotFoundError: No module named 'hypothesis'`).  The `pyproject.toml`
  already listed `hypothesis` as a dev dependency — this was a gap in the
  environment setup, not a missing declaration.
- **Why:** Phase 1 gate criterion: all four conservation-law constraint
  builders implemented with property-based hypothesis tests passing.  KCL is
  Law 1; three more laws remain before the gate criterion is met.
- **Result:** 200 tests pass; precommit gate green.  The Law 1 constraint
  module is ready for consumption by the reconstruction solver.
- **Failed:** Nothing significant.  Two unit tests initially had missing
  `NodeBalance` entries for target nodes (tests were written assuming ghost
  nodes with E=0, but the large residuals at those nodes caused spurious gate
  violations).  Fixed by explicitly balancing all nodes in the test.
- **Next:** Law 2 checker (`claimweb.constraints.double_entry`) per TODO.

### 2026-05-15 — fetcher: FhlbCombinedFetcher (project plan §10.4)

- **What:** Implemented `claimweb/fetchers/fhlb_combined.py` — the FHLB Office
  of Finance Combined Financial Report fetcher.  Created:
  - `FhlbCombinedFetcher(BaseFetcher)` — full fetcher class with all four
    required methods: `list_available_periods`, `acquire`, `parse`, `validate`.
  - `parse()` extracts two categories of A3 arcs from the PDF:
    (1) a system-wide insurance-member aggregate from the "ADVANCES OUTSTANDING
    BY MEMBER TYPE" table (amounts in billions, converted to millions); and
    (2) individual named-insurer arcs from the "TOP TEN ADVANCE USERS" table
    (amounts already in millions).
  - Entity-name → canonical node-ID mapping for ~40 major U.S. life insurer
    legal entities.  Unknown names go to `claimweb/registry/unmapped/` for
    human review rather than being silently dropped.
  - Arc direction: source = insurer (borrower/liability side), target = fhlb:system
    (lender/asset side), consistent with `x_{ij}^k` convention in project plan §1.
  - `validate()` checks: presence of the insurance aggregate, plausibility of
    the aggregate amount, and that the sum of named-member arcs ≤ the aggregate.
  - `list_available_periods()` and `acquire()` scrape the FHLB-OF index page to
    enumerate and download quarterly PDFs, with local caching by SHA-256.
  Created `tests/fixtures/fhlb_combined/generate_fixture.py` — a standalone
  script that generates a minimal but pdfplumber-readable PDF fixture capturing
  the key tables of the 2024-Q4 Combined Financial Report.  The fixture is
  committed as `tests/fixtures/fhlb_combined/2024-Q4-combined-financial-report.pdf`.
  Created `tests/unit/test_fhlb_combined.py` with 44 unit tests and 2 integration
  tests (marked `@pytest.mark.integration`; excluded from the fast suite):
  - `TestLabelToPeriod`: 13 tests across all quarter-label formats
  - `TestCanonicalizeMemberName`: known names, case insensitivity, unmapped
  - `TestSlug`: truncation, special chars, unicode
  - `TestFhlbCombinedFetcherParse`: 14 tests — aggregate arc, named arcs,
    dollar amounts, ArcClass, DataQualityFlag, provenance, SHA-256 matching
  - `TestFhlbCombinedFetcherValidate`: 5 tests — clean path, NO_FACTS,
    MISSING_AGGREGATE, NAMED_EXCEEDS_AGGREGATE, LOW_INSURANCE_TOTAL
  - `TestFhlbCombinedFetcherRun`: convenience method round-trip
  - `TestFhlbCombinedFetcherProperties`: round-trip via to_dict/from_dict
  Also: added `integration` pytest marker to `pyproject.toml`; updated
  `scripts/precommit_gate.sh` to exclude integration tests from the fast suite
  (`-m "not integration"`).
- **Why:** Phase 1 gate criterion: `FhlbCombinedFetcher` implemented end-to-end
  with unit tests on a captured fixture (per `docs/PHASE_GATES.md`). This is the
  "first fetcher" called out in project plan §35 as the Week 1 action item.
  Spawned the `data-source-investigator` subagent first as required by the
  fetcher-author skill; it confirmed the URL pattern and PDF structure.
- **Result:** 165 tests pass (121 pre-existing + 44 new); ruff clean; precommit
  gate green. `claimweb.fetchers.fhlb_combined` importable; `FhlbCombinedFetcher`
  exported at `claimweb.fetchers` level (via `__init__.py` update needed — see
  below). Parse output on fixture: 1 aggregate arc (89,700 M USD for insurance
  members) + 5 named-insurer arcs; validation is clean.
- **Failed:** Two regex bugs found during testing and fixed:
  (1) `_MEMBER_ROW_RE` used `\s{2,}` (required 2+ spaces), but pdfplumber
  collapses multiple spaces in a BT/Tj text stream to single spaces — changed to
  `\s+`. (2) `_QUARTER_LABEL_RE` had `31` hardcoded for month-day, but June and
  September quarters end on the 30th — changed to `\d{1,2}`.
  The uv-managed pytest tool environment needed `httpx`, `pdfplumber`,
  `beautifulsoup4`, and `lxml` added (same one-time environment issue as previous
  session; same fix: `uv tool install pytest --with ...`).
- **Next:** `claimweb.constraints.kcl` — balance-sheet identity (Law 1) checker.
  Per project plan §1.1 and `constraint-author` skill. Property-based tests
  verifying soundness, completeness, stability, independence.

### 2026-05-15 — fetcher: BaseFetcher abstraction and ArcFact schema

- **What:** Implemented `claimweb/fetchers/base.py` — the foundational
  abstraction every CLAIM-WEB fetcher must subclass.  Defined:
  - `Period` — validated quarter-identifier class (`YYYY-Q[1-4]`);
    hashable, orderable, serialisable.
  - `ArcClass` (A1..A12) — arc-instrument taxonomy from project plan §4.
  - `DataQualityFlag` (7 values) — epistemic taxonomy from §12, with
    `priority` property for comparison.
  - `RawDataHandle` — frozen dataclass referencing acquired raw files
    by path and SHA-256 (content-addressing per fetcher-author skill).
  - `ArcFact` — frozen dataclass; Decimal dollar amounts (millions USD);
    mandatory provenance fields enforced in `__post_init__`; `to_dict` /
    `from_dict` for JSON-safe round-tripping.
  - `ValidationIssue` / `ValidationReport` — discrepancy reporting;
    `is_clean` determined solely by absence of error-severity issues.
  - `BaseFetcher` — ABC with `__init_subclass__` guard requiring
    `source_id` and `cadence`; abstract `list_available_periods`,
    `acquire`, `parse`, `validate`; convenience `run` method.
  Created `tests/unit/test_fetchers_base.py` with 48 tests:
  - Parametrised unit tests for `Period` validity, ordering, hashing.
  - `ArcClass` (12 members) and `DataQualityFlag` (7 members, priority).
  - `ArcFact` construction validation (rejects float/int dollars, bad
    measurement basis, empty provenance, wrong sha256 length).
  - Hypothesis property-based tests: `to_dict`/`from_dict` round-trip
    (200 examples), JSON round-trip (200 examples), Decimal precision
    preservation (200 examples), all field invariants.
  - `ValidationReport` issue accumulation and `is_clean` semantics.
  - `BaseFetcher` subclass contract enforcement.
- **Why:** Phase 1 gate criterion: `BaseFetcher` abstraction in
  `claimweb/fetchers/base.py` implemented and unit-tested (per
  `docs/PHASE_GATES.md`).  Without this, no concrete fetcher can be
  written — every downstream module depends on `ArcFact`.
- **Result:** 121 tests pass (73 skeleton + 48 new); ruff clean;
  precommit gate green.  All property-based tests run 200 examples each.
  `claimweb.fetchers.base` importable; all types exported at module level.
- **Failed:** The precommit gate's `pytest` invocation uses a uv-managed
  tool environment (`/root/.local/share/uv/tools/pytest/`) that is
  separate from the system Python where `pip install -e ".[dev]"` places
  hypothesis.  Running `pytest` from PATH failed with
  `ModuleNotFoundError: No module named 'hypothesis'` even though
  `python -m pytest` worked fine.  Fixed by running
  `uv tool install pytest --with hypothesis` to add hypothesis to the
  uv-tool environment.  This is a one-time environment setup step.
- **Next:** `claimweb.fetchers.fhlb_combined` — FHLB Office of Finance
  Combined Financial Report fetcher (project plan §10.4).  Before writing
  code, spawn the `data-source-investigator` subagent to characterise the
  source.  Unit test on a captured fixture under
  `tests/fixtures/fhlb_combined/`.

### 2026-05-15 — Bootstrap: package skeleton

- **What:** Scaffolded the `claimweb/` Python package per project plan §18.
  Created `pyproject.toml` with all §19 dependencies (pinned floors with
  reasonable ceilings); created every package and module per §18 layout
  with module-level docstrings cross-referencing the relevant plan sections;
  created `tests/` (unit / integration / validation tiers per §21) with
  a single bootstrap smoke test that imports every subpackage and module
  and verifies each has a docstring; created `data/raw/`,
  `data/normalized/`, `data/output/`, and `notebooks/` placeholders;
  updated `.gitignore` to (a) preserve the `data/raw/.gitkeep` and (b)
  ignore future `data/output/network/*/v*/` directories.
- **Why:** Phase 1 gate criterion: `claimweb/` Python package skeleton
  exists with module-level docstrings referencing project-plan sections,
  and `pyproject.toml` exists with pinned dependencies (per
  `/claimweb-bootstrap` and `docs/PHASE_GATES.md`).
- **Result:** 73 unit tests pass; ruff clean; precommit gate green.
  Every module compiles (`python -m py_compile`) and every subpackage
  imports cleanly. Package installs with `pip install -e ".[dev]"` against
  the locked-in dependency set.
- **Failed:** The precommit gate's `scripts/check_data_sources.sh` was
  matching its own pattern strings inside `scripts/` (false positives on
  `guard_no_paid_aggregator.sh`, `guard_bash.sh`, `post_edit_check.sh`,
  and itself). The enforcement scripts have to contain the pattern strings
  in order to detect them; the grep was just too aggressive. Fixed by
  adding `--exclude` filters for the four enforcement scripts. This is
  a harness bug that would have blocked every subsequent commit until
  resolved.
- **Next:** First fetcher — `claimweb.fetchers.base` (the `BaseFetcher`
  abstraction and `ArcFact` schema) per the `fetcher-author` skill.
  Once that lands, `claimweb.fetchers.fhlb_combined` follows.

---

## Standing reminders

When updating this file:
- Don't delete old entries even when retired — they're the project's institutional memory.
- Cross-reference project-plan section numbers when relevant.
- If you tried an approach that failed, describe *why* it failed — not just that it did. Future sessions read this and will repeat the failure without that context.
- When a phase gate is hit (see `docs/PHASE_GATES.md`), add a phase-gate entry summarizing the gate criteria and how they were met.

