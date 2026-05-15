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

### 2026-05-15 — constraints: Z.1 sectoral aggregate (Law 3)

- **What:** Implemented `claimweb/constraints/sectoral.py` — Law 3 checker
  per project plan §1.1.  Full public interface:
  - `SectorMap` — `dict[str, str]` mapping node_id → sector_id (e.g.
    `"sector:life_insurance_companies"`).
  - `SectoralTotals` — `dict[tuple[sector_id, instrument_class_value, side], Decimal]`
    mapping each *(sector, instrument, "asset"|"liab")* triple to the expected
    Z.1 published total in millions USD.
  - `SectoralViolation` / `SectoralResult` — typed result objects with full
    provenance strings.
  - `build_sectoral_rows(facts, *, period, sector_map, sectoral_totals)` —
    compiles one `LinearConstraint` per *(sector, instrument, side)* entry.
    Asset-side constraints sum outgoing arcs from sector nodes; liability-side
    constraints sum incoming arcs to sector nodes.  `DIRECT_MEASURED` arcs fold
    into the RHS as constants; all other arcs remain as variables.
  - `check_sectoral(network, *, sector_map, sectoral_totals, tol)` — directly
    verifies Law 3 on a concrete solved network; returns `SectoralResult` with
    per-violation detail.
  - `_provenance_parts(provenance)` — parses *(sector_id, instrument_class_value,
    side)* back out of a provenance string (used by property tests).
  Default tolerance: 0.1 % relative with $0.1 M absolute floor.
  Test file: `tests/unit/test_sectoral.py` — 37 tests (5 property-based via
  hypothesis: soundness, completeness, stability, independence; 32 unit tests
  covering empty inputs, asset/liability sides, multi-sector networks, period
  filtering, provenance format, tolerance thresholds).  437 total pass;
  precommit gate green.
- **Why:** Phase 1 constraint checkers; enables the solver to receive Z.1
  sectoral boundary conditions as hard linear equalities.
- **Result:** `claimweb/constraints/sectoral.py`, `tests/unit/test_sectoral.py`
- **Failed:** None.
- **Next:** Law 4 (`flow_funds.py`) and then `compile.py` to aggregate all four
  laws into a single sparse linear system.

### 2026-05-15 — fetcher: SEC XBRL companyfacts for LIFE_INSURERS panel

- **What:** Implemented `claimweb/fetchers/sec_xbrl.py` — `SecXbrlFetcher` for
  the LIFE_INSURERS panel. SEC EDGAR companyfacts API (§10.2).
  Created:
  - `LIFE_INSURERS` — panel of 15 major U.S. public life insurance holding
    companies mapped to zero-padded 10-digit CIKs: MetLife, Prudential,
    Lincoln National, Principal Financial, Aflac, Unum, Reinsurance Group of
    America, Brighthouse Financial, Equitable Holdings, Voya Financial, CNO
    Financial Group, Jackson Financial, Globe Life, American Equity Investment
    Life, F&G Annuities & Life.  Mutual companies (New York Life, Northwestern
    Mutual, MassMutual, etc.) excluded — no SEC filings.
  - `_CIK_TO_ENTITY` — reverse lookup from CIK to canonical entity node ID.
  - `_TAG_MAP` — 9 us-gaap XBRL tags mapped to (ArcClass, source_template,
    target_template): `Assets`, `Liabilities`, `StockholdersEquity`,
    `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`
    (Law 1 balance-sheet marginals); `AdvancesFromFederalHomeLoanBanks` (A3);
    `SecuritiesSoldUnderAgreementsToRepurchase` (A4);
    `PayablesForCollateralUnderSecuritiesLoanedAndOtherTransactions` (A5);
    `PolicyholderAccountBalance`, `PolicyholderContractDeposits` (A1).
  - `_end_date_to_period(end_date_str)` — converts SEC end-date string to
    Period for calendar-year filers; non-standard fiscal-year-end returns None.
  - `_period_to_end_date(period)` — returns quarter-end date for a Period.
  - `_extract_best_fact(entries, period)` — selects the best XBRL tag entry
    for a period: primary forms (10-K/10-Q) > amendments; entries with
    `frame` (undimensioned totals) > segment facts; latest filed wins ties.
    Returns (amount_millions, accession_number, filing_form).
  - `SecXbrlFetcher.list_available_periods()` — enumerates periods from the
    `Assets` tag of the first panel entity; calls `_ensure_bundle()`.
  - `SecXbrlFetcher.acquire(period)` — downloads full companyfacts JSON for
    each CIK once (14-day cache window); returns handle referencing all CIK
    JSONs with the target period embedded.
  - `SecXbrlFetcher.parse(handle)` — for each CIK JSON, extracts facts for
    `handle.period` across all mapped tags; resolves CIK to canonical entity
    ID; emits `DIRECT_MEASURED` / `stock_eop` ArcFacts with full provenance
    (URL, filing accession, XBRL tag name, SHA-256 of JSON).
  - `SecXbrlFetcher.validate(facts)` — checks: (1) at least one ArcFact
    emitted, (2) no negative amounts, (3) at least one entity's total assets
    exceeds the $10 B plausibility floor.
  Dollar amounts: raw USD from API divided by Decimal("0.000001") to millions.
  Rate-limiting: User-Agent header per EDGAR guidelines; 14-day cache avoids
  repeated downloads.
  Created `tests/fixtures/sec_xbrl/__init__.py` and
  `tests/fixtures/sec_xbrl/CIK0001099219.json` — MetLife fixture with 2024-Q3
  and 2024-Q4 data covering Assets, Liabilities, StockholdersEquity,
  AdvancesFromFederalHomeLoanBanks, SecuritiesSoldUnderAgreementsToRepurchase,
  PolicyholderAccountBalance (with both framed and unframed entries to test
  selection logic), and
  PayablesForCollateralUnderSecuritiesLoanedAndOtherTransactions.
  Created `tests/unit/test_sec_xbrl.py` with 81 tests:
  - 3 property-based (hypothesis): schema validity of emitted ArcFacts;
    USD→MM conversion exactness; Period↔end-date roundtrip.
  - 78 unit tests covering: _end_date_to_period (valid dates, invalid dates,
    return type, year/quarter fields), _period_to_end_date (all quarters,
    roundtrip), _extract_best_fact (no match, amount conversion, USD→MM,
    primary-form preference, frame preference, latest-filed tiebreak, accn/form
    returned, amendment fallback, Decimal type, empty input),
    SecXbrlFetcher.parse (Q4 facts, Assets tag, FHLB arc direction/class/amount,
    repo arc, policyholder balance with frame selection, sec-lending arc, Q3
    data, empty for unknown period, data_quality_flag, measurement_basis,
    provenance_source, provenance_url, provenance_filing, SHA-256 length, period
    matches handle, assets arc direction, liabilities arc direction, unknown CIK
    skipped, integer CIK in JSON handled), SecXbrlFetcher.validate (clean,
    empty→error, negative→warning, implausible assets→error, plausible clean,
    source_id), SecXbrlFetcher.list_available_periods (sorted, Period objects,
    includes 2024-Q4, includes 2024-Q3), attributes (source_id, cadence),
    LIFE_INSURERS panel (nonempty, 10-digit CIKs, insurer: prefix, CIK
    uniqueness, entity-ID uniqueness, reverse-map consistency, MET present,
    ≥10 entities), _TAG_MAP (nonempty, 3-tuple values, ArcClass types, assets
    tag present, FHLB→A3, repo→A4, sec-lending→A5, {entity_id} in templates).

- **Why:** TODO.md Now item: `claimweb.fetchers.sec_xbrl` — SEC companyfacts
  XBRL fetcher for the LIFE_INSURERS panel, per project plan §10.2.

- **Result:**
  - `claimweb/fetchers/sec_xbrl.py` — 310 lines
  - `tests/fixtures/sec_xbrl/CIK0001099219.json` — MetLife fixture
  - `tests/unit/test_sec_xbrl.py` — 81 tests; 400 total pass; gate green

- **Next:** `claimweb.constraints.sectoral` (Law 3) — Z.1 sectoral aggregate
  boundary conditions (project plan §1.1).

### 2026-05-15 — constraints: double-entry consistency (Law 2) with property tests

- **What:** Implemented `claimweb/constraints/double_entry.py` — Law 2 checker.
  Created:
  - `InstrumentTotals` — type alias `dict[str, Decimal]` mapping ArcClass value
    to the expected aggregate total in millions USD (from Z.1 or FHLB data).
  - `DoubleEntryViolation` — per-instrument violation dataclass with `actual_total`,
    `expected_total`, `residual` (signed), `arc_count`, and `provenance`.
  - `DoubleEntryResult` — aggregate result of `check_double_entry` with
    `instrument_count` (all instruments present in network) and `checked_count`
    (instruments actually verified against a boundary term).
  - `build_double_entry_rows(facts, *, period, boundary_terms)` — emits one
    `LinearConstraint` per instrument in `boundary_terms`.  `DIRECT_MEASURED`
    arcs are folded into the RHS as known constants; all other arcs remain as
    variables.  When `boundary_terms` is `None` or empty, the law is trivially
    satisfied for a closed network and an empty `ConstraintSet` is returned.
  - `check_double_entry(network, *, boundary_terms, tol)` — verifies that the
    total arc amount for each instrument matches its expected total within
    tolerance (default 0.5 % relative; $0.1 M absolute floor per conservation-
    laws rule).  Without `boundary_terms` the check trivially passes (no
    external reference).
  - `_provenance_instrument(provenance)` — helper to extract the instrument
    class value from a double-entry provenance string.
  Shared types (`ArcKey`, `LinearConstraint`, `ConstraintSet`, `NetworkState`,
  `_group_arcs_by_key_with_flag`, `_ZERO`) are imported from `kcl.py` rather
  than duplicated.  Tolerance follows the conservation-laws rule: 0.5 % for
  instrument-level double-entry (wider than the 0.01 % node-level KCL because
  boundary effects are more pronounced at instrument level).
  Created `tests/unit/test_double_entry.py` with 40 tests:
  - 5 property-based (hypothesis): soundness, soundness via check, completeness,
    stability, independence.
  - 35 unit tests covering: empty facts, None/empty boundary_terms, single unknown
    arc, single DIRECT_MEASURED arc (matrix_row empty), mixed arcs, period
    filtering, multiple instruments, instrument absent from boundary_terms, zero
    boundary with no arcs, constraint provenance format, unknowns list, check with
    no boundary terms, check satisfied, violated (too high and too low), violation
    below and above tolerance, zero boundary with non-zero actual, instrument not
    in network, multiple instruments with partial violation, result counts, empty
    network, provenance key info, arc_count, type fields, _provenance_instrument
    helper, signed residual, absolute floor behaviour.
  Also fixed the precommit gate environment: the `pytest` uv tool was missing
  `hypothesis`, `httpx`, `beautifulsoup4`, `pdfplumber`, `lxml`, `pymupdf`, and
  `tabula-py`. Installed all via `uv tool install pytest --with ...`.  Gate now
  passes clean (319 tests, 2 deselected integration tests).

- **Why:** TODO.md Now item: Law 2 (double-entry) constraint module per project
  plan §1.1 and constraint-author skill.

- **Result:**
  - `claimweb/constraints/double_entry.py` — 214 lines
  - `tests/unit/test_double_entry.py` — 40 tests; 319 total pass; gate green

- **Next:** `claimweb.constraints.sectoral` (Law 3) — Z.1 sectoral aggregate
  boundary conditions (project plan §1.1).

### 2026-05-15 — fetcher: FRB Z.1 Financial Accounts of the United States (project plan §10.1)

- **What:** Implemented `claimweb/fetchers/z1.py` — the Z.1 sectoral-constraint
  fetcher.  Created:
  - `Z1Fetcher(BaseFetcher)` — full fetcher class with all four required
    methods: `list_available_periods`, `acquire`, `parse`, `validate`.
  - `_parse_ddp_csv(content)` — flexible parser for the FRB Data Download
    Program CSV format (`layout=seriescolumn`).  Handles: preamble rows
    ("Unique Identifier", "Series Description", "Multiplier", "Currency"),
    blank separators, data rows, NA/ND/dot missing-value tokens, quoted
    fields, and both ISO-date and "YYYY:QN" period notation.
  - `_date_str_to_period(date_str)` — robust quarter inference from ISO
    dates (end-of-quarter: March/June/Sep/Dec; start-of-quarter: Jan/Apr/
    Jul/Oct), YYYY:QN, and YYYY-QN formats.
  - `_multiplier_factor(label)` — converts "Millions"/"Billions"/"Thousands"
    multiplier labels to the Decimal scaling factor needed to normalize raw
    values to millions of USD.
  - `_SERIES_MAP` — 27 key series from the 7 target tables (L.116, L.121,
    L.207, L.208, L.211, L.226, L.227) mapped to (ArcClass, source_node_id,
    target_node_id).  Covers: FHLB advances (A3), MMF shares (A8), agency/GSE
    securities (A10), repos (A4), commercial paper/FABCP (A2), bank deposits
    (A9), and sector totals (A12).  Unmapped series are logged at DEBUG and
    skipped.
  - Bundle-based caching: `acquire(period)` downloads all 7 table CSVs from
    the FRB DDP once per 30-day window; cached at `data/raw/z1/bundle/`.
    `parse(handle)` filters the complete historical CSV to the requested period.
  - `validate(facts)` checks: non-empty parse, all amounts non-negative,
    life-insurer total financial assets ≥ $500B plausibility floor.
  - Data quality: all emitted arcs are `DIRECT_MEASURED`; measurement basis
    is `stock_eop` (end-of-period stocks).
  Created fixture files at `tests/fixtures/z1/` (7 synthetic CSVs, one per
  target table) and `tests/unit/test_z1.py` with 79 tests:
  - `TestDateStrToPeriod` — 17 tests covering end-of-quarter, start-of-quarter,
    YYYY:QN, YYYY-QN, whitespace tolerance, and invalid inputs.
  - `TestMultiplierFactor` — 10 tests covering all three multiplier labels
    and case-insensitivity.
  - `TestParseDdpCsv` — 11 tests covering series-ID extraction, multiplier
    application, NA/dot handling, no-preamble CSV, Billions multiplier, empty
    content, and quoted fields.
  - `TestZ1FetcherParse` — 16 tests covering: arc-fact presence, correct period,
    DIRECT_MEASURED flag, stock_eop basis, provenance fields, Decimal amounts,
    SHA256, FHLB-advance arc direction (source=life_insurance, target=fhlb),
    MMF-share arc direction (source=mmf, target=life_insurance), Billions
    multiplier application (L208 fixture), missing-period empty result,
    empty-handle empty result, unmapped-series skipping, and multi-table coverage.
  - `TestZ1FetcherValidate` — 5 tests covering clean path, empty facts,
    negative amounts, implausible LIC total assets, and source_id correctness.
  - `TestZ1ListAvailablePeriods` — 2 tests verifying sorted list and Period
    type.
  - `TestZ1FetcherAttributes` — 4 attribute tests.
  - `TestSeriesMap` — 8 invariant tests on the series-map structure.
  - 3 property-based tests (hypothesis): ArcFact schema compliance for all
    emitted facts, multiplier associativity, date→period validity.
- **Why:** Phase 1 gate criterion: `Z1Fetcher` implemented for tables L.116,
  L.121, L.207, L.208, L.211, L.226, L.227.  Provides the sectoral boundary
  conditions (Law 3) needed by the forthcoming `sectoral` constraint module.
- **Result:** 279 tests pass; precommit gate green.  Gate criterion
  "Z1Fetcher implemented for tables L.116, L.121, L.207, L.208, L.211,
  L.226, L.227" is now met.
- **Failed:** Nothing significant.  The property-based test initially used a
  `tmp_path` pytest fixture with `@given`, which hypothesis flags as a health
  violation (fixture not reset between generated examples).  Fixed by adding
  `suppress_health_check=[HealthCheck.function_scoped_fixture]` and adding a
  `mkdir(parents=True, exist_ok=True)` call in `_make_handle()`.
  pdfplumber, beautifulsoup4, and lxml were not installed in the `uv`-managed
  pytest tool environment (causing a collection error for test_fhlb_combined.py
  when running the full gate).  Fixed with `uv tool install --with ...`.
- **Next:** Law 2 checker (`claimweb.constraints.double_entry`) per TODO.

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

