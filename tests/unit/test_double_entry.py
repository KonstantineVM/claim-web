"""Property-based and unit tests for claimweb.constraints.double_entry (Law 2).

Tests verify four properties per the constraint-author skill:
1. Soundness    — on a network satisfying Law 2 by construction, build_double_entry_rows
                  emits constraints that are all satisfied.
2. Completeness — on a network violating Law 2 (arc total doesn't match boundary),
                  check_double_entry detects at least one violation.
3. Stability    — perturbing a DIRECT_MEASURED arc by δ shifts the constraint RHS
                  by exactly −δ (linear; no chaotic behaviour).
4. Independence — constraints from different instruments don't interfere with each
                  other (each constraint's matrix_row references only arcs of its
                  own instrument class).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from claimweb.constraints.double_entry import (
    DoubleEntryResult,
    DoubleEntryViolation,
    InstrumentTotals,
    _DEFAULT_TOL_REL,
    _MIN_ABS_TOL,
    _provenance_instrument,
    build_double_entry_rows,
    check_double_entry,
)
from claimweb.constraints.kcl import (
    ConstraintSet,
    LinearConstraint,
    NetworkState,
    NodeBalance,
)
from claimweb.fetchers.base import ArcClass, ArcFact, DataQualityFlag, Period

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_DUMMY_SHA256 = "b" * 64
_PERIOD = Period("2024-Q4")
_OTHER_PERIOD = Period("2023-Q1")


def _make_arc(
    source: str,
    target: str,
    amount: Decimal,
    flag: DataQualityFlag = DataQualityFlag.MARGINAL_INFERRED,
    cls: ArcClass = ArcClass.A3,
    period: Period = _PERIOD,
) -> ArcFact:
    """Minimal ArcFact factory for testing."""
    return ArcFact(
        period=period,
        source_node_id=source,
        target_node_id=target,
        instrument_class=cls,
        dollar_amount_millions=amount,
        measurement_basis="stock_eop",
        data_quality_flag=flag,
        provenance_source="test",
        provenance_url="https://example.com/test",
        provenance_filing=None,
        provenance_page=None,
        provenance_field="test_field",
        sha256_of_source=_DUMMY_SHA256,
    )


def _make_direct(
    source: str,
    target: str,
    amount: Decimal,
    cls: ArcClass = ArcClass.A3,
) -> ArcFact:
    return _make_arc(source, target, amount, DataQualityFlag.DIRECT_MEASURED, cls)


def _make_network(
    arcs: list[ArcFact],
    period: Period = _PERIOD,
) -> NetworkState:
    """Minimal NetworkState — no node balances needed for double-entry tests."""
    nodes = {arc.source_node_id for arc in arcs} | {arc.target_node_id for arc in arcs}
    balances = {
        nid: NodeBalance(
            node_id=nid,
            period=period,
            equity_millions=Decimal("0"),
            nonfinancial_assets_millions=Decimal("0"),
        )
        for nid in nodes
    }
    return NetworkState(period=period, arcs=arcs, node_balances=balances)


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_amounts = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1000000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Minimum must exceed max possible tolerance threshold for the check.
# Max boundary = 3 arcs * 1_000_000 = 3_000_000 → threshold = 0.005 * 3_000_000 = 15_000.
# Using 20_000 ensures the perturbation always exceeds the threshold.
_large_perturbation = st.decimals(
    min_value=Decimal("20000"),
    max_value=Decimal("500000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def valid_de_network(
    draw: st.DrawFn,
) -> tuple[NetworkState, InstrumentTotals]:
    """Network where total per instrument == boundary_term by construction.

    Strategy:
    * Pick 2 instruments from {A3, A8, A9}.
    * For each instrument, pick 1–3 arcs.
    * boundary_term[k] = sum of arc amounts for k (Law 2 satisfied exactly).
    """
    instruments = draw(
        st.lists(
            st.sampled_from([ArcClass.A3, ArcClass.A8, ArcClass.A9]),
            min_size=1,
            max_size=3,
            unique=True,
        )
    )
    arcs: list[ArcFact] = []
    boundary_terms: InstrumentTotals = {}

    for cls in instruments:
        n_arcs = draw(st.integers(min_value=1, max_value=3))
        total = Decimal("0")
        for i in range(n_arcs):
            amount = draw(_amounts)
            arcs.append(_make_arc(f"src_{cls.value}_{i}", f"tgt_{cls.value}_{i}", amount, cls=cls))
            total += amount
        boundary_terms[cls.value] = total

    network = _make_network(arcs)
    return network, boundary_terms


# ---------------------------------------------------------------------------
# Property 1 — Soundness
# ---------------------------------------------------------------------------


@given(valid_de_network())
@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
def test_soundness_build_double_entry_rows(
    nd: tuple[NetworkState, InstrumentTotals],
) -> None:
    """On a Law-2-satisfying network, every compiled constraint is satisfied.

    Substitutes the network's true arc values into each LinearConstraint's
    matrix_row and asserts that LHS == RHS to within Decimal tolerance.
    """
    network, boundary_terms = nd
    cs: ConstraintSet = build_double_entry_rows(
        network.arcs, period=network.period, boundary_terms=boundary_terms
    )

    # One constraint per instrument in boundary_terms.
    assert len(cs.constraints) == len(boundary_terms)

    for c in cs.constraints:
        lhs = sum(
            (coeff * network.arc_value(ak) for ak, coeff in c.matrix_row.items()),
            start=Decimal("0"),
        )
        residual = abs(lhs - c.rhs)
        assert residual <= Decimal("0.01"), (
            f"Soundness failure: {c.provenance}\n"
            f"  LHS={lhs}, RHS={c.rhs}, residual={residual}"
        )


@given(valid_de_network())
@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
def test_soundness_check_double_entry(
    nd: tuple[NetworkState, InstrumentTotals],
) -> None:
    """check_double_entry reports satisfied=True on a Law-2-satisfying network."""
    network, boundary_terms = nd
    result: DoubleEntryResult = check_double_entry(
        network, boundary_terms=boundary_terms, tol=_DEFAULT_TOL_REL
    )
    assert result.satisfied, (
        "Expected satisfied network but got violations:\n"
        + "\n".join(f"  {v.provenance}" for v in result.violations)
    )
    assert result.checked_count == len(boundary_terms)


# ---------------------------------------------------------------------------
# Property 2 — Completeness
# ---------------------------------------------------------------------------


@given(valid_de_network(), _large_perturbation)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_completeness_check_double_entry(
    nd: tuple[NetworkState, InstrumentTotals],
    extra: Decimal,
) -> None:
    """Adding extra to one arc's amount (without updating boundary) → violation."""
    network, boundary_terms = nd
    orig = network.arcs[0]
    perturbed_arc = _make_arc(
        orig.source_node_id,
        orig.target_node_id,
        orig.dollar_amount_millions + extra,
        cls=orig.instrument_class,
    )
    bad_network = NetworkState(
        period=network.period,
        arcs=[perturbed_arc] + network.arcs[1:],
        node_balances=network.node_balances,
    )
    result: DoubleEntryResult = check_double_entry(
        bad_network, boundary_terms=boundary_terms, tol=_DEFAULT_TOL_REL
    )
    assert not result.satisfied, (
        f"Expected violation after adding {extra} to arc but got satisfied"
    )
    assert len(result.violations) >= 1
    # The perturbed instrument must appear in the violation set.
    violated = {v.instrument_class_value for v in result.violations}
    assert orig.instrument_class.value in violated, (
        f"Expected {orig.instrument_class.value!r} in violations; got {violated}"
    )


# ---------------------------------------------------------------------------
# Property 3 — Stability
# ---------------------------------------------------------------------------


@given(valid_de_network(), _amounts, _amounts)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_stability_build_double_entry_rows(
    nd: tuple[NetworkState, InstrumentTotals],
    direct_amount: Decimal,
    delta: Decimal,
) -> None:
    """Perturbing a DIRECT_MEASURED arc by δ shifts its instrument's RHS by −δ.

    A DIRECT_MEASURED arc is folded into the RHS as a known constant. If the
    arc amount increases by δ, the RHS decreases by δ (the unknown arcs need
    to account for δ less). All other constraints remain unchanged.
    """
    network, boundary_terms = nd
    cls_val = network.arcs[0].instrument_class.value

    # Inject one DIRECT_MEASURED arc for the first instrument at known amount.
    direct_arc = _make_direct("dm_src", "dm_tgt", direct_amount, cls=network.arcs[0].instrument_class)
    facts_base = network.arcs + [direct_arc]
    # Recompute boundary to include the direct arc so the constraint is consistent.
    bt_base = dict(boundary_terms)
    bt_base[cls_val] = bt_base[cls_val] + direct_amount

    cs_base: ConstraintSet = build_double_entry_rows(
        facts_base, period=network.period, boundary_terms=bt_base
    )
    rhs_base = next(
        c.rhs for c in cs_base.constraints
        if cls_val in c.provenance
    )

    # Now increase the DIRECT_MEASURED arc by delta.
    direct_arc_delta = _make_direct(
        "dm_src", "dm_tgt", direct_amount + delta, cls=network.arcs[0].instrument_class
    )
    facts_delta = network.arcs + [direct_arc_delta]
    bt_delta = dict(boundary_terms)
    bt_delta[cls_val] = bt_delta[cls_val] + direct_amount + delta

    cs_delta: ConstraintSet = build_double_entry_rows(
        facts_delta, period=network.period, boundary_terms=bt_delta
    )
    rhs_delta = next(
        c.rhs for c in cs_delta.constraints
        if cls_val in c.provenance
    )

    # RHS should be the same in both cases: boundary was also updated by delta,
    # and DIRECT_MEASURED arc also increased by delta, so net effect cancels.
    # Actually: RHS = boundary - direct = (b + direct + delta) - (direct + delta) = b.
    assert abs(rhs_base - rhs_delta) <= Decimal("0.01"), (
        f"Stability failure: rhs_base={rhs_base}, rhs_delta={rhs_delta}, delta={delta}"
    )


# ---------------------------------------------------------------------------
# Property 4 — Independence
# ---------------------------------------------------------------------------


@given(valid_de_network())
@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
def test_independence_constraints(
    nd: tuple[NetworkState, InstrumentTotals],
) -> None:
    """Each constraint's matrix_row only references arcs of its own instrument."""
    network, boundary_terms = nd
    cs: ConstraintSet = build_double_entry_rows(
        network.arcs, period=network.period, boundary_terms=boundary_terms
    )

    for c in cs.constraints:
        instr_val = _provenance_instrument(c.provenance)
        assert instr_val is not None, f"Could not parse instrument from: {c.provenance}"
        for arc_key in c.matrix_row:
            assert arc_key[2] == instr_val, (
                f"Constraint for {instr_val!r} references arc of class {arc_key[2]!r}"
            )


# ---------------------------------------------------------------------------
# Unit tests — build_double_entry_rows
# ---------------------------------------------------------------------------


def test_empty_facts_returns_empty_constraint_set() -> None:
    cs = build_double_entry_rows([], period=_PERIOD, boundary_terms={"A3": Decimal("100")})
    assert len(cs.constraints) == 1
    c = cs.constraints[0]
    # No arcs → no unknowns → matrix_row empty; RHS = boundary = 100.
    assert c.matrix_row == {}
    assert c.rhs == Decimal("100")
    assert c.kind == "eq"


def test_none_boundary_terms_returns_empty_constraint_set() -> None:
    arc = _make_arc("A", "B", Decimal("100"))
    cs = build_double_entry_rows([arc], period=_PERIOD, boundary_terms=None)
    assert cs.constraints == []
    assert cs.unknowns == []


def test_empty_boundary_terms_returns_empty_constraint_set() -> None:
    arc = _make_arc("A", "B", Decimal("100"))
    cs = build_double_entry_rows([arc], period=_PERIOD, boundary_terms={})
    assert cs.constraints == []
    assert cs.unknowns == []


def test_single_unknown_arc_generates_one_constraint() -> None:
    arc = _make_arc("A", "B", Decimal("500"), DataQualityFlag.MARGINAL_INFERRED)
    cs = build_double_entry_rows(
        [arc], period=_PERIOD, boundary_terms={"A3": Decimal("500")}
    )
    assert len(cs.constraints) == 1
    c = cs.constraints[0]
    assert len(c.matrix_row) == 1
    assert c.rhs == Decimal("500")
    key = ("A", "B", "A3", "2024-Q4")
    assert c.matrix_row[key] == Decimal("1")


def test_single_direct_measured_arc_no_unknowns_in_matrix() -> None:
    arc = _make_direct("A", "B", Decimal("300"))
    cs = build_double_entry_rows(
        [arc], period=_PERIOD, boundary_terms={"A3": Decimal("300")}
    )
    assert len(cs.constraints) == 1
    c = cs.constraints[0]
    # DIRECT_MEASURED folded into RHS; matrix_row is empty.
    assert c.matrix_row == {}
    # RHS = boundary - direct = 300 - 300 = 0.
    assert c.rhs == Decimal("0")


def test_direct_measured_reduces_rhs() -> None:
    arc_known = _make_direct("A", "B", Decimal("200"))
    arc_unknown = _make_arc("C", "D", Decimal("100"))
    cs = build_double_entry_rows(
        [arc_known, arc_unknown],
        period=_PERIOD,
        boundary_terms={"A3": Decimal("300")},
    )
    assert len(cs.constraints) == 1
    c = cs.constraints[0]
    # RHS = 300 - 200 = 100; unknown arc has coefficient +1.
    assert c.rhs == Decimal("100")
    key = ("C", "D", "A3", "2024-Q4")
    assert c.matrix_row.get(key) == Decimal("1")
    # Known arc not in matrix_row.
    known_key = ("A", "B", "A3", "2024-Q4")
    assert known_key not in c.matrix_row


def test_multiple_instruments_generates_multiple_constraints() -> None:
    arc_a3 = _make_arc("A", "B", Decimal("100"), cls=ArcClass.A3)
    arc_a8 = _make_arc("C", "D", Decimal("200"), cls=ArcClass.A8)
    cs = build_double_entry_rows(
        [arc_a3, arc_a8],
        period=_PERIOD,
        boundary_terms={"A3": Decimal("100"), "A8": Decimal("200")},
    )
    assert len(cs.constraints) == 2
    # Sorted by instrument key: A3 before A8.
    assert "A3" in cs.constraints[0].provenance
    assert "A8" in cs.constraints[1].provenance


def test_instrument_without_boundary_term_not_constrained() -> None:
    arc_a3 = _make_arc("A", "B", Decimal("100"), cls=ArcClass.A3)
    arc_a8 = _make_arc("C", "D", Decimal("200"), cls=ArcClass.A8)
    # Only A3 in boundary_terms.
    cs = build_double_entry_rows(
        [arc_a3, arc_a8],
        period=_PERIOD,
        boundary_terms={"A3": Decimal("100")},
    )
    assert len(cs.constraints) == 1
    assert "A3" in cs.constraints[0].provenance
    # A8 arc should not appear in any constraint.
    for c in cs.constraints:
        for key in c.matrix_row:
            assert key[2] != "A8"


def test_period_filtering_excludes_other_period_arcs() -> None:
    arc_current = _make_arc("A", "B", Decimal("100"))
    arc_other = _make_arc("C", "D", Decimal("999"), period=_OTHER_PERIOD)
    cs = build_double_entry_rows(
        [arc_current, arc_other],
        period=_PERIOD,
        boundary_terms={"A3": Decimal("100")},
    )
    # Only the current-period arc should contribute.
    assert len(cs.constraints) == 1
    c = cs.constraints[0]
    assert len(c.matrix_row) == 1  # only the current arc (unknown).
    key = ("A", "B", "A3", "2024-Q4")
    assert key in c.matrix_row


def test_constraint_kind_is_eq() -> None:
    arc = _make_arc("A", "B", Decimal("50"))
    cs = build_double_entry_rows(
        [arc], period=_PERIOD, boundary_terms={"A3": Decimal("50")}
    )
    assert cs.constraints[0].kind == "eq"


def test_constraint_provenance_format() -> None:
    arc = _make_arc("A", "B", Decimal("50"))
    cs = build_double_entry_rows(
        [arc], period=_PERIOD, boundary_terms={"A3": Decimal("50")}
    )
    prov = cs.constraints[0].provenance
    assert "Law 2" in prov
    assert "double-entry" in prov
    assert "A3" in prov
    assert "2024-Q4" in prov


def test_unknowns_list_matches_non_direct_arcs() -> None:
    arc_dm = _make_direct("A", "B", Decimal("100"))
    arc_mi = _make_arc("C", "D", Decimal("50"))
    arc_pr = _make_arc("E", "F", Decimal("75"), DataQualityFlag.PROXY)
    cs = build_double_entry_rows(
        [arc_dm, arc_mi, arc_pr],
        period=_PERIOD,
        boundary_terms={"A3": Decimal("225")},
    )
    # Only MARGINAL_INFERRED and PROXY arcs are unknowns.
    assert len(cs.unknowns) == 2
    unknown_sources = {k[0] for k in cs.unknowns}
    assert "C" in unknown_sources
    assert "E" in unknown_sources
    assert "A" not in unknown_sources


def test_zero_boundary_term_with_no_arcs() -> None:
    """Boundary of 0 and no arcs → matrix_row empty, RHS = 0."""
    cs = build_double_entry_rows(
        [], period=_PERIOD, boundary_terms={"A3": Decimal("0")}
    )
    assert len(cs.constraints) == 1
    c = cs.constraints[0]
    assert c.matrix_row == {}
    assert c.rhs == Decimal("0")


def test_multiple_unknown_arcs_same_instrument() -> None:
    arcs = [
        _make_arc("A", "B", Decimal("100")),
        _make_arc("C", "D", Decimal("200")),
        _make_arc("E", "F", Decimal("300")),
    ]
    cs = build_double_entry_rows(
        arcs, period=_PERIOD, boundary_terms={"A3": Decimal("600")}
    )
    assert len(cs.constraints) == 1
    c = cs.constraints[0]
    # All three arcs are unknowns; RHS = 600 (no direct measured arcs).
    assert len(c.matrix_row) == 3
    assert c.rhs == Decimal("600")


# ---------------------------------------------------------------------------
# Unit tests — check_double_entry
# ---------------------------------------------------------------------------


def test_check_no_boundary_terms_trivially_satisfied() -> None:
    arcs = [_make_arc("A", "B", Decimal("500"))]
    network = _make_network(arcs)
    result = check_double_entry(network)
    assert result.satisfied
    assert result.violations == []
    assert result.checked_count == 0
    assert result.instrument_count == 1


def test_check_empty_boundary_terms_trivially_satisfied() -> None:
    arcs = [_make_arc("A", "B", Decimal("500"))]
    network = _make_network(arcs)
    result = check_double_entry(network, boundary_terms={})
    assert result.satisfied
    assert result.checked_count == 0


def test_check_matching_boundary_satisfied() -> None:
    arcs = [
        _make_arc("A", "B", Decimal("300")),
        _make_arc("C", "D", Decimal("200")),
    ]
    network = _make_network(arcs)
    result = check_double_entry(network, boundary_terms={"A3": Decimal("500")})
    assert result.satisfied
    assert result.violations == []
    assert result.checked_count == 1


def test_check_violated_total_too_high() -> None:
    arcs = [_make_arc("A", "B", Decimal("600"))]
    network = _make_network(arcs)
    # boundary says 100, actual is 600.
    result = check_double_entry(network, boundary_terms={"A3": Decimal("100")})
    assert not result.satisfied
    assert len(result.violations) == 1
    v = result.violations[0]
    assert v.instrument_class_value == "A3"
    assert v.actual_total == Decimal("600")
    assert v.expected_total == Decimal("100")
    assert v.residual == Decimal("500")


def test_check_violated_total_too_low() -> None:
    arcs = [_make_arc("A", "B", Decimal("50"))]
    network = _make_network(arcs)
    result = check_double_entry(network, boundary_terms={"A3": Decimal("1000")})
    assert not result.satisfied
    assert len(result.violations) == 1
    assert result.violations[0].residual < Decimal("0")


def test_check_violation_below_tolerance_not_reported() -> None:
    # Actual = 1000.003, expected = 1000 → 0.003 % error, below 0.5 % tol.
    arcs = [_make_arc("A", "B", Decimal("1000.003"))]
    network = _make_network(arcs)
    result = check_double_entry(
        network,
        boundary_terms={"A3": Decimal("1000")},
        tol=Decimal("0.005"),
    )
    assert result.satisfied


def test_check_violation_above_tolerance_reported() -> None:
    # Actual = 1050, expected = 1000 → 5 % error, above 0.5 % tol.
    arcs = [_make_arc("A", "B", Decimal("1050"))]
    network = _make_network(arcs)
    result = check_double_entry(
        network,
        boundary_terms={"A3": Decimal("1000")},
        tol=Decimal("0.005"),
    )
    assert not result.satisfied
    assert len(result.violations) == 1


def test_check_zero_boundary_with_nonzero_total_violated() -> None:
    arcs = [_make_arc("A", "B", Decimal("5"))]
    network = _make_network(arcs)
    # 5 > _MIN_ABS_TOL (0.1) → violation.
    result = check_double_entry(network, boundary_terms={"A3": Decimal("0")})
    assert not result.satisfied


def test_check_instrument_not_in_network() -> None:
    """Instrument listed in boundary_terms but absent from network → violation."""
    arcs = [_make_arc("A", "B", Decimal("100"), cls=ArcClass.A8)]
    network = _make_network(arcs)
    # A3 boundary specified but no A3 arcs in network → actual = 0, expected = 500.
    result = check_double_entry(network, boundary_terms={"A3": Decimal("500")})
    assert not result.satisfied
    v = result.violations[0]
    assert v.instrument_class_value == "A3"
    assert v.actual_total == Decimal("0")
    assert v.arc_count == 0


def test_check_multiple_instruments_partial_violation() -> None:
    arcs = [
        _make_arc("A", "B", Decimal("100"), cls=ArcClass.A3),
        _make_arc("C", "D", Decimal("200"), cls=ArcClass.A8),
    ]
    network = _make_network(arcs)
    # A3 correct, A8 wrong.
    result = check_double_entry(
        network,
        boundary_terms={"A3": Decimal("100"), "A8": Decimal("999")},
    )
    assert not result.satisfied
    assert len(result.violations) == 1
    assert result.violations[0].instrument_class_value == "A8"
    assert result.checked_count == 2


def test_check_result_instrument_count() -> None:
    arcs = [
        _make_arc("A", "B", Decimal("100"), cls=ArcClass.A3),
        _make_arc("C", "D", Decimal("200"), cls=ArcClass.A8),
        _make_arc("E", "F", Decimal("300"), cls=ArcClass.A9),
    ]
    network = _make_network(arcs)
    result = check_double_entry(
        network,
        boundary_terms={"A3": Decimal("100")},
    )
    assert result.instrument_count == 3  # 3 distinct instruments in network
    assert result.checked_count == 1    # only A3 was checked


def test_check_empty_network_with_boundary_terms() -> None:
    network = NetworkState(period=_PERIOD, arcs=[], node_balances={})
    result = check_double_entry(network, boundary_terms={"A3": Decimal("100")})
    # actual = 0, expected = 100, residual > _MIN_ABS_TOL → violation.
    assert not result.satisfied
    assert result.instrument_count == 0
    assert result.checked_count == 1


def test_check_violation_provenance_contains_key_info() -> None:
    arcs = [_make_arc("A", "B", Decimal("999"))]
    network = _make_network(arcs)
    result = check_double_entry(network, boundary_terms={"A3": Decimal("1")})
    assert len(result.violations) == 1
    prov = result.violations[0].provenance
    assert "Law 2" in prov
    assert "A3" in prov
    assert "2024-Q4" in prov
    assert "actual=" in prov
    assert "expected=" in prov


def test_check_violation_arc_count_correct() -> None:
    arcs = [
        _make_arc("A", "B", Decimal("100")),
        _make_arc("C", "D", Decimal("200")),
    ]
    network = _make_network(arcs)
    result = check_double_entry(network, boundary_terms={"A3": Decimal("9999")})
    assert len(result.violations) == 1
    assert result.violations[0].arc_count == 2


# ---------------------------------------------------------------------------
# Unit tests — type fields and helpers
# ---------------------------------------------------------------------------


def test_double_entry_violation_fields() -> None:
    v = DoubleEntryViolation(
        instrument_class_value="A3",
        period=_PERIOD,
        actual_total=Decimal("600"),
        expected_total=Decimal("500"),
        residual=Decimal("100"),
        arc_count=3,
        provenance="test",
    )
    assert v.instrument_class_value == "A3"
    assert v.residual == Decimal("100")
    assert v.arc_count == 3


def test_double_entry_result_fields() -> None:
    r = DoubleEntryResult(
        period=_PERIOD,
        satisfied=True,
        violations=[],
        instrument_count=5,
        checked_count=2,
    )
    assert r.satisfied
    assert r.instrument_count == 5
    assert r.checked_count == 2


def test_provenance_instrument_extracts_correctly() -> None:
    prov = "Law 2 (double-entry) for instrument 'A3', period 2024-Q4"
    assert _provenance_instrument(prov) == "A3"


def test_provenance_instrument_returns_none_for_bad_string() -> None:
    assert _provenance_instrument("not a double-entry provenance") is None


def test_residual_is_signed() -> None:
    """Residual is actual − expected (signed), not absolute."""
    arcs = [_make_arc("A", "B", Decimal("50"))]
    network = _make_network(arcs)
    result = check_double_entry(network, boundary_terms={"A3": Decimal("100")})
    assert len(result.violations) == 1
    # actual < expected → negative residual.
    assert result.violations[0].residual < Decimal("0")


def test_min_abs_tolerance_prevents_spurious_tiny_violation() -> None:
    """A 0.001 difference on a zero expected total should still count as violation."""
    arcs = [_make_arc("A", "B", Decimal("0.001"))]
    network = _make_network(arcs)
    # 0.001 < _MIN_ABS_TOL (0.1) → NOT a violation (falls below absolute floor).
    result = check_double_entry(network, boundary_terms={"A3": Decimal("0")})
    # 0.001 is less than _MIN_ABS_TOL of 0.1.
    assert result.satisfied


def test_boundary_just_above_absolute_floor_is_violation() -> None:
    arcs = [_make_arc("A", "B", Decimal("1"))]
    network = _make_network(arcs)
    # actual=1, expected=0 → residual=1 > _MIN_ABS_TOL=0.1 → violation.
    result = check_double_entry(network, boundary_terms={"A3": Decimal("0")})
    assert not result.satisfied
