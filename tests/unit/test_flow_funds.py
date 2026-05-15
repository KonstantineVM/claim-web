"""Property-based and unit tests for claimweb.constraints.flow_funds (Law 4).

Tests verify four properties per the constraint-author skill:
1. Soundness      — on a pair of networks satisfying Law 4 by construction,
                    build_flow_funds_rows emits constraints that are all satisfied
                    when arc values are substituted in.
2. Completeness   — on a network pair violating Law 4 (one arc perturbed),
                    check_flow_funds detects at least one violation.
3. Stability      — changing F by delta shifts the constraint RHS by exactly
                    delta (linear; no chaotic behaviour).
4. Independence   — each constraint's matrix_row references only ArcKeys for
                    its own (src, tgt, instr) triple across the two periods.
5. Provenance     — _provenance_arc round-trips through every generated
                    provenance string.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from claimweb.constraints.flow_funds import (
    FlowFundsResult,
    FlowFundsViolation,
    FlowKey,
    FlowTerms,
    RevaluationTerms,
    _DEFAULT_TOL_REL,
    _MIN_ABS_TOL,
    _provenance_arc,
    build_flow_funds_rows,
    check_flow_funds,
)
from claimweb.constraints.kcl import (
    ArcKey,
    ConstraintSet,
    LinearConstraint,
    NetworkState,
    NodeBalance,
)
from claimweb.fetchers.base import ArcClass, ArcFact, DataQualityFlag, Period

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_DUMMY_SHA256 = "d" * 64
_PERIOD_FROM = Period("2024-Q3")
_PERIOD_TO = Period("2024-Q4")
_OTHER_PERIOD = Period("2023-Q1")


def _make_arc(
    source: str,
    target: str,
    amount: Decimal,
    flag: DataQualityFlag = DataQualityFlag.MARGINAL_INFERRED,
    cls: ArcClass = ArcClass.A3,
    period: Period = _PERIOD_TO,
) -> ArcFact:
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
    period: Period = _PERIOD_TO,
) -> ArcFact:
    return _make_arc(source, target, amount, DataQualityFlag.DIRECT_MEASURED, cls, period)


def _make_network(
    arcs: list[ArcFact],
    period: Period,
) -> NetworkState:
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


def _empty_network(period: Period) -> NetworkState:
    return NetworkState(period=period, arcs=[], node_balances={})


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_amounts = st.decimals(
    min_value=Decimal("1.00"),
    max_value=Decimal("500000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_flows = st.decimals(
    min_value=Decimal("-100000"),
    max_value=Decimal("100000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_large_perturbation = st.decimals(
    min_value=Decimal("10000"),
    max_value=Decimal("500000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_small_delta = st.decimals(
    min_value=Decimal("1"),
    max_value=Decimal("1000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_INSTRUMENTS = [ArcClass.A3, ArcClass.A4, ArcClass.A8]


@st.composite
def valid_flow_network_pair(
    draw: st.DrawFn,
) -> tuple[NetworkState, NetworkState, FlowTerms, RevaluationTerms]:
    """Two consecutive NetworkStates satisfying Law 4 by construction.

    Strategy:
    * Pick 1–3 (src, tgt, instr) arcs.
    * For each arc draw x(t), F, R freely.
    * Set x(t+1) = x(t) + F + R (ensures Law 4 holds exactly).
    * Return (network_from, network_to, flow_terms, revaluation_terms).
    """
    n_arcs = draw(st.integers(min_value=1, max_value=3))
    arcs_from: list[ArcFact] = []
    arcs_to: list[ArcFact] = []
    flow_terms: FlowTerms = {}
    revaluation_terms: RevaluationTerms = {}

    used_keys: set[tuple[str, str, str]] = set()

    for i in range(n_arcs):
        src = f"node_a{i}"
        tgt = f"node_b{i}"
        instr = draw(st.sampled_from(_INSTRUMENTS))
        key: FlowKey = (src, tgt, instr.value)

        if key in used_keys:
            continue
        used_keys.add(key)

        amount_from = draw(_amounts)
        F = draw(_flows)
        R = draw(_flows)
        amount_to = amount_from + F + R  # Law 4 satisfied by construction

        # Ensure amount_to is non-negative (arc amounts can't be negative in practice).
        if amount_to < Decimal("0"):
            # Adjust F so amount_to = 1.00
            F = Decimal("1.00") - amount_from - R
            amount_to = amount_from + F + R

        arcs_from.append(_make_arc(src, tgt, amount_from, cls=instr, period=_PERIOD_FROM))
        arcs_to.append(_make_arc(src, tgt, amount_to, cls=instr, period=_PERIOD_TO))
        flow_terms[key] = F
        revaluation_terms[key] = R

    if not arcs_from:
        # Fallback: ensure at least one arc
        amount_from = Decimal("1000.00")
        F = Decimal("50.00")
        R = Decimal("0.00")
        amount_to = amount_from + F + R
        key = ("node_a0", "node_b0", "A3")
        arcs_from = [_make_arc("node_a0", "node_b0", amount_from, period=_PERIOD_FROM)]
        arcs_to = [_make_arc("node_a0", "node_b0", amount_to, period=_PERIOD_TO)]
        flow_terms = {key: F}
        revaluation_terms = {key: R}

    network_from = _make_network(arcs_from, _PERIOD_FROM)
    network_to = _make_network(arcs_to, _PERIOD_TO)
    return network_from, network_to, flow_terms, revaluation_terms


# ---------------------------------------------------------------------------
# Property 1 — Soundness (build_flow_funds_rows)
# ---------------------------------------------------------------------------


@given(valid_flow_network_pair())
@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
def test_soundness_build_flow_funds_rows(
    quad: tuple[NetworkState, NetworkState, FlowTerms, RevaluationTerms],
) -> None:
    """On a Law-4-satisfying pair, every compiled constraint is satisfied.

    Substitutes the network arc values into each constraint's matrix_row
    and verifies LHS == RHS to within Decimal('0.01') tolerance.
    """
    network_from, network_to, flow_terms, revaluation_terms = quad
    cs: ConstraintSet = build_flow_funds_rows(
        network_from.arcs,
        network_to.arcs,
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms=flow_terms,
        revaluation_terms=revaluation_terms,
    )

    # Build a combined arc-value lookup covering both periods.
    def arc_value(key: ArcKey) -> Decimal:
        src, tgt, instr_val, period_str = key
        period = _PERIOD_FROM if period_str == str(_PERIOD_FROM) else _PERIOD_TO
        network = network_from if period == _PERIOD_FROM else network_to
        return network.arc_value(key)

    for c in cs.constraints:
        lhs = sum(
            (coeff * arc_value(ak) for ak, coeff in c.matrix_row.items()),
            start=Decimal("0"),
        )
        residual = abs(lhs - c.rhs)
        assert residual <= Decimal("0.01"), (
            f"Soundness failure: {c.provenance}\n"
            f"  LHS={lhs}, RHS={c.rhs}, residual={residual}"
        )


# ---------------------------------------------------------------------------
# Property 1b — Soundness (check_flow_funds)
# ---------------------------------------------------------------------------


@given(valid_flow_network_pair())
@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
def test_soundness_check_flow_funds(
    quad: tuple[NetworkState, NetworkState, FlowTerms, RevaluationTerms],
) -> None:
    """check_flow_funds reports satisfied=True on a Law-4-satisfying pair."""
    network_from, network_to, flow_terms, revaluation_terms = quad
    result: FlowFundsResult = check_flow_funds(
        network_from,
        network_to,
        flow_terms=flow_terms,
        revaluation_terms=revaluation_terms,
        tol=Decimal("0.0001"),
    )
    assert result.satisfied, (
        "Expected satisfied network pair but got violations:\n"
        + "\n".join(f"  {v.provenance}" for v in result.violations)
    )
    assert result.checked_count == len(flow_terms)


# ---------------------------------------------------------------------------
# Property 2 — Completeness
# ---------------------------------------------------------------------------


@given(valid_flow_network_pair(), _large_perturbation)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_completeness_check_flow_funds(
    quad: tuple[NetworkState, NetworkState, FlowTerms, RevaluationTerms],
    extra: Decimal,
) -> None:
    """Perturbing one arc by a large amount triggers a Law 4 violation."""
    network_from, network_to, flow_terms, revaluation_terms = quad
    # Pick the first flow_key and inflate amount_to by 'extra'.
    flow_key = next(iter(sorted(flow_terms)))
    src, tgt, instr_val = flow_key
    instr_cls = ArcClass(instr_val)

    # Rebuild network_to with the perturbed arc.
    perturbed_arcs = []
    found = False
    for arc in network_to.arcs:
        if (
            arc.source_node_id == src
            and arc.target_node_id == tgt
            and arc.instrument_class.value == instr_val
        ):
            perturbed_arcs.append(
                _make_arc(
                    src,
                    tgt,
                    arc.dollar_amount_millions + extra,
                    cls=instr_cls,
                    period=_PERIOD_TO,
                )
            )
            found = True
        else:
            perturbed_arcs.append(arc)

    if not found:
        # Arc was absent in network_to; add a perturbed version.
        perturbed_arcs.append(_make_arc(src, tgt, extra, cls=instr_cls, period=_PERIOD_TO))

    perturbed_network_to = _make_network(perturbed_arcs, _PERIOD_TO)

    result: FlowFundsResult = check_flow_funds(
        network_from,
        perturbed_network_to,
        flow_terms=flow_terms,
        revaluation_terms=revaluation_terms,
        tol=Decimal("0.0001"),
    )
    assert not result.satisfied, (
        "Expected at least one violation after large perturbation but got satisfied=True"
    )
    assert len(result.violations) >= 1


# ---------------------------------------------------------------------------
# Property 3 — Stability
# ---------------------------------------------------------------------------


@given(valid_flow_network_pair(), _small_delta)
@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
def test_stability_flow_term_shift(
    quad: tuple[NetworkState, NetworkState, FlowTerms, RevaluationTerms],
    delta: Decimal,
) -> None:
    """Changing F by delta shifts the constraint RHS by exactly delta."""
    network_from, network_to, flow_terms, revaluation_terms = quad
    flow_key = next(iter(sorted(flow_terms)))

    cs_original = build_flow_funds_rows(
        network_from.arcs,
        network_to.arcs,
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms=flow_terms,
        revaluation_terms=revaluation_terms,
    )

    # Bump F for the chosen key.
    perturbed_flow = dict(flow_terms)
    perturbed_flow[flow_key] = flow_terms[flow_key] + delta

    cs_perturbed = build_flow_funds_rows(
        network_from.arcs,
        network_to.arcs,
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms=perturbed_flow,
        revaluation_terms=revaluation_terms,
    )

    # Locate the constraint for this flow_key in both sets.
    src, tgt, instr_val = flow_key
    p_from_str = str(_PERIOD_FROM)
    p_to_str = str(_PERIOD_TO)
    target_prov_fragment = f"arc {src!r} -> {tgt!r} instrument {instr_val!r}"

    def find_c(cs: ConstraintSet) -> LinearConstraint | None:
        for c in cs.constraints:
            if target_prov_fragment in c.provenance:
                return c
        return None

    c_orig = find_c(cs_original)
    c_pert = find_c(cs_perturbed)

    assert c_orig is not None
    assert c_pert is not None
    rhs_diff = c_pert.rhs - c_orig.rhs
    assert abs(rhs_diff - delta) <= Decimal("0.00001"), (
        f"Stability failure: expected RHS shift {delta}, got {rhs_diff}"
    )


# ---------------------------------------------------------------------------
# Property 4 — Independence
# ---------------------------------------------------------------------------


@given(valid_flow_network_pair())
@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
def test_independence_matrix_row_references(
    quad: tuple[NetworkState, NetworkState, FlowTerms, RevaluationTerms],
) -> None:
    """Each constraint's matrix_row only references ArcKeys for its own arc."""
    network_from, network_to, flow_terms, revaluation_terms = quad
    cs: ConstraintSet = build_flow_funds_rows(
        network_from.arcs,
        network_to.arcs,
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms=flow_terms,
        revaluation_terms=revaluation_terms,
    )
    p_from_str = str(_PERIOD_FROM)
    p_to_str = str(_PERIOD_TO)

    for c in cs.constraints:
        parsed = _provenance_arc(c.provenance)
        assert parsed is not None, f"Could not parse provenance: {c.provenance}"
        exp_src, exp_tgt, exp_instr, exp_pf, exp_pt = parsed

        for key in c.matrix_row:
            key_src, key_tgt, key_instr, key_period = key
            assert key_src == exp_src, f"Wrong src in matrix_row for {c.provenance}"
            assert key_tgt == exp_tgt, f"Wrong tgt in matrix_row for {c.provenance}"
            assert key_instr == exp_instr, f"Wrong instr in matrix_row for {c.provenance}"
            assert key_period in {p_from_str, p_to_str}, (
                f"ArcKey period {key_period!r} not in "
                f"{{{p_from_str!r}, {p_to_str!r}}} for {c.provenance}"
            )


# ---------------------------------------------------------------------------
# Property 5 — Provenance round-trip
# ---------------------------------------------------------------------------


@given(valid_flow_network_pair())
@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
def test_provenance_round_trip(
    quad: tuple[NetworkState, NetworkState, FlowTerms, RevaluationTerms],
) -> None:
    """_provenance_arc correctly parses every generated provenance string."""
    network_from, network_to, flow_terms, revaluation_terms = quad
    cs: ConstraintSet = build_flow_funds_rows(
        network_from.arcs,
        network_to.arcs,
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms=flow_terms,
        revaluation_terms=revaluation_terms,
    )

    for c in cs.constraints:
        parsed = _provenance_arc(c.provenance)
        assert parsed is not None, f"_provenance_arc failed on: {c.provenance!r}"
        src, tgt, instr_val, p_from, p_to = parsed
        assert p_from == str(_PERIOD_FROM)
        assert p_to == str(_PERIOD_TO)


# ===========================================================================
# Unit tests
# ===========================================================================

# ---------------------------------------------------------------------------
# Empty / None inputs
# ---------------------------------------------------------------------------


def test_none_flow_terms_returns_empty_constraint_set():
    cs = build_flow_funds_rows(
        [], [],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms=None,
    )
    assert cs.constraints == []
    assert cs.unknowns == []


def test_empty_flow_terms_returns_empty_constraint_set():
    cs = build_flow_funds_rows(
        [], [],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={},
    )
    assert cs.constraints == []
    assert cs.unknowns == []


def test_check_flow_funds_none_flow_terms_trivially_passes():
    net_f = _empty_network(_PERIOD_FROM)
    net_t = _empty_network(_PERIOD_TO)
    result = check_flow_funds(net_f, net_t, flow_terms=None)
    assert result.satisfied is True
    assert result.checked_count == 0
    assert result.violations == []


def test_check_flow_funds_empty_flow_terms_trivially_passes():
    net_f = _empty_network(_PERIOD_FROM)
    net_t = _empty_network(_PERIOD_TO)
    result = check_flow_funds(net_f, net_t, flow_terms={})
    assert result.satisfied is True
    assert result.checked_count == 0


# ---------------------------------------------------------------------------
# Single arc — both periods unknown
# ---------------------------------------------------------------------------


def test_single_arc_both_unknown_coefficient_structure():
    """Constraint has +1 for key_to and -1 for key_from."""
    arc_f = _make_arc("A", "B", Decimal("1000"), period=_PERIOD_FROM)
    arc_t = _make_arc("A", "B", Decimal("1100"), period=_PERIOD_TO)
    flow_terms: FlowTerms = {("A", "B", "A3"): Decimal("100")}

    cs = build_flow_funds_rows(
        [arc_f], [arc_t],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms=flow_terms,
    )

    assert len(cs.constraints) == 1
    c = cs.constraints[0]

    key_from: ArcKey = ("A", "B", "A3", str(_PERIOD_FROM))
    key_to: ArcKey = ("A", "B", "A3", str(_PERIOD_TO))

    assert key_from in c.matrix_row
    assert key_to in c.matrix_row
    assert c.matrix_row[key_from] == Decimal("-1")
    assert c.matrix_row[key_to] == Decimal("1")
    assert c.rhs == Decimal("100")  # F=100, R=0
    assert c.kind == "eq"


def test_single_arc_both_unknown_unknowns_list():
    arc_f = _make_arc("A", "B", Decimal("500"), period=_PERIOD_FROM)
    arc_t = _make_arc("A", "B", Decimal("600"), period=_PERIOD_TO)
    cs = build_flow_funds_rows(
        [arc_f], [arc_t],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("A", "B", "A3"): Decimal("100")},
    )
    key_from: ArcKey = ("A", "B", "A3", str(_PERIOD_FROM))
    key_to: ArcKey = ("A", "B", "A3", str(_PERIOD_TO))
    assert key_from in cs.unknowns
    assert key_to in cs.unknowns


# ---------------------------------------------------------------------------
# Single arc — period_from DIRECT_MEASURED
# ---------------------------------------------------------------------------


def test_period_from_direct_measured_folded_into_rhs():
    """When x(t) is DIRECT_MEASURED, it folds into RHS: rhs = F + R + a_from."""
    arc_f = _make_direct("A", "B", Decimal("800"), period=_PERIOD_FROM)
    arc_t = _make_arc("A", "B", Decimal("900"), period=_PERIOD_TO)
    F = Decimal("50")
    R = Decimal("50")

    cs = build_flow_funds_rows(
        [arc_f], [arc_t],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("A", "B", "A3"): F},
        revaluation_terms={("A", "B", "A3"): R},
    )

    assert len(cs.constraints) == 1
    c = cs.constraints[0]

    key_from: ArcKey = ("A", "B", "A3", str(_PERIOD_FROM))
    key_to: ArcKey = ("A", "B", "A3", str(_PERIOD_TO))

    # x(t) is known — should NOT appear in matrix_row
    assert key_from not in c.matrix_row
    # x(t+1) is unknown — should appear with coefficient +1
    assert key_to in c.matrix_row
    assert c.matrix_row[key_to] == Decimal("1")
    # RHS = F + R + a_from = 50 + 50 + 800 = 900
    assert c.rhs == Decimal("900")


def test_period_from_direct_not_in_unknowns():
    arc_f = _make_direct("A", "B", Decimal("100"), period=_PERIOD_FROM)
    arc_t = _make_arc("A", "B", Decimal("200"), period=_PERIOD_TO)
    cs = build_flow_funds_rows(
        [arc_f], [arc_t],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("A", "B", "A3"): Decimal("100")},
    )
    key_from: ArcKey = ("A", "B", "A3", str(_PERIOD_FROM))
    assert key_from not in cs.unknowns


# ---------------------------------------------------------------------------
# Single arc — period_to DIRECT_MEASURED
# ---------------------------------------------------------------------------


def test_period_to_direct_measured_folded_into_rhs():
    """When x(t+1) is DIRECT_MEASURED, it folds into RHS: rhs = F + R - a_to."""
    arc_f = _make_arc("A", "B", Decimal("800"), period=_PERIOD_FROM)
    arc_t = _make_direct("A", "B", Decimal("900"), period=_PERIOD_TO)
    F = Decimal("100")
    R = Decimal("0")

    cs = build_flow_funds_rows(
        [arc_f], [arc_t],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("A", "B", "A3"): F},
        revaluation_terms={("A", "B", "A3"): R},
    )

    assert len(cs.constraints) == 1
    c = cs.constraints[0]

    key_from: ArcKey = ("A", "B", "A3", str(_PERIOD_FROM))
    key_to: ArcKey = ("A", "B", "A3", str(_PERIOD_TO))

    # x(t+1) is known — should NOT appear in matrix_row
    assert key_to not in c.matrix_row
    # x(t) is unknown — should appear with coefficient -1
    assert key_from in c.matrix_row
    assert c.matrix_row[key_from] == Decimal("-1")
    # RHS = F + R - a_to = 100 + 0 - 900 = -800
    assert c.rhs == Decimal("-800")


# ---------------------------------------------------------------------------
# Both periods DIRECT_MEASURED
# ---------------------------------------------------------------------------


def test_both_periods_direct_measured_empty_matrix_row():
    """When both arcs are DIRECT_MEASURED, matrix_row is empty (pure check)."""
    arc_f = _make_direct("A", "B", Decimal("800"), period=_PERIOD_FROM)
    arc_t = _make_direct("A", "B", Decimal("850"), period=_PERIOD_TO)
    F = Decimal("50")
    R = Decimal("0")

    cs = build_flow_funds_rows(
        [arc_f], [arc_t],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("A", "B", "A3"): F},
    )

    assert len(cs.constraints) == 1
    c = cs.constraints[0]
    # matrix_row empty: both known
    assert c.matrix_row == {}
    # rhs = F + R + a_from - a_to = 50 + 0 + 800 - 850 = 0
    assert c.rhs == Decimal("0")
    assert len(cs.unknowns) == 0


def test_both_periods_direct_measured_consistent_rhs_zero():
    """A perfectly consistent arc pair produces rhs=0 with empty matrix_row."""
    amount_from = Decimal("1000")
    F = Decimal("200")
    R = Decimal("50")
    amount_to = amount_from + F + R  # = 1250

    arc_f = _make_direct("X", "Y", amount_from, period=_PERIOD_FROM)
    arc_t = _make_direct("X", "Y", amount_to, period=_PERIOD_TO)

    cs = build_flow_funds_rows(
        [arc_f], [arc_t],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("X", "Y", "A3"): F},
        revaluation_terms={("X", "Y", "A3"): R},
    )
    c = cs.constraints[0]
    assert c.matrix_row == {}
    assert c.rhs == Decimal("0")


# ---------------------------------------------------------------------------
# Arc absent from one period
# ---------------------------------------------------------------------------


def test_arc_absent_from_period_from_no_key_from_in_row():
    """When arc doesn't exist in period_from (new arc), only +1 for key_to."""
    arc_t = _make_arc("A", "B", Decimal("300"), period=_PERIOD_TO)
    F = Decimal("300")

    cs = build_flow_funds_rows(
        [], [arc_t],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("A", "B", "A3"): F},
    )

    c = cs.constraints[0]
    key_from: ArcKey = ("A", "B", "A3", str(_PERIOD_FROM))
    key_to: ArcKey = ("A", "B", "A3", str(_PERIOD_TO))

    assert key_from not in c.matrix_row
    assert key_to in c.matrix_row
    assert c.matrix_row[key_to] == Decimal("1")
    assert c.rhs == Decimal("300")  # F=300, x(t)=0 (absent)


def test_arc_absent_from_period_to_no_key_to_in_row():
    """When arc is absent in period_to (terminated arc), only -1 for key_from."""
    arc_f = _make_arc("A", "B", Decimal("500"), period=_PERIOD_FROM)
    F = Decimal("-500")  # full redemption

    cs = build_flow_funds_rows(
        [arc_f], [],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("A", "B", "A3"): F},
    )

    c = cs.constraints[0]
    key_from: ArcKey = ("A", "B", "A3", str(_PERIOD_FROM))
    key_to: ArcKey = ("A", "B", "A3", str(_PERIOD_TO))

    assert key_to not in c.matrix_row
    assert key_from in c.matrix_row
    assert c.matrix_row[key_from] == Decimal("-1")
    assert c.rhs == Decimal("-500")  # F=-500, x(t+1)=0 (absent)


def test_arc_absent_from_both_periods_empty_matrix_row():
    """Arc in flow_terms but present in neither network → empty matrix_row."""
    cs = build_flow_funds_rows(
        [], [],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("A", "B", "A3"): Decimal("0")},
    )
    c = cs.constraints[0]
    assert c.matrix_row == {}
    assert c.rhs == Decimal("0")


# ---------------------------------------------------------------------------
# Flow and revaluation terms
# ---------------------------------------------------------------------------


def test_zero_flow_term_rhs_equals_revaluation():
    arc_f = _make_arc("A", "B", Decimal("500"), period=_PERIOD_FROM)
    arc_t = _make_arc("A", "B", Decimal("510"), period=_PERIOD_TO)
    R = Decimal("10")
    cs = build_flow_funds_rows(
        [arc_f], [arc_t],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("A", "B", "A3"): Decimal("0")},
        revaluation_terms={("A", "B", "A3"): R},
    )
    c = cs.constraints[0]
    assert c.rhs == Decimal("10")  # F=0, R=10


def test_negative_flow_term_net_redemption():
    arc_f = _make_arc("A", "B", Decimal("1000"), period=_PERIOD_FROM)
    arc_t = _make_arc("A", "B", Decimal("700"), period=_PERIOD_TO)
    F = Decimal("-300")  # net redemption
    cs = build_flow_funds_rows(
        [arc_f], [arc_t],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("A", "B", "A3"): F},
    )
    c = cs.constraints[0]
    assert c.rhs == Decimal("-300")


def test_revaluation_absent_defaults_to_zero():
    arc_f = _make_arc("A", "B", Decimal("200"), period=_PERIOD_FROM)
    arc_t = _make_arc("A", "B", Decimal("250"), period=_PERIOD_TO)
    F = Decimal("50")
    cs = build_flow_funds_rows(
        [arc_f], [arc_t],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("A", "B", "A3"): F},
        # revaluation_terms omitted
    )
    c = cs.constraints[0]
    assert c.rhs == Decimal("50")  # F=50, R=0


def test_positive_revaluation_adds_to_rhs():
    arc_f = _make_arc("A", "B", Decimal("1000"), period=_PERIOD_FROM)
    arc_t = _make_arc("A", "B", Decimal("1150"), period=_PERIOD_TO)
    F = Decimal("100")
    R = Decimal("50")
    cs = build_flow_funds_rows(
        [arc_f], [arc_t],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("A", "B", "A3"): F},
        revaluation_terms={("A", "B", "A3"): R},
    )
    c = cs.constraints[0]
    assert c.rhs == Decimal("150")  # F + R = 150


def test_negative_revaluation_subtracts_from_rhs():
    arc_f = _make_arc("A", "B", Decimal("1000"), period=_PERIOD_FROM)
    arc_t = _make_arc("A", "B", Decimal("950"), period=_PERIOD_TO)
    F = Decimal("0")
    R = Decimal("-50")
    cs = build_flow_funds_rows(
        [arc_f], [arc_t],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("A", "B", "A3"): F},
        revaluation_terms={("A", "B", "A3"): R},
    )
    c = cs.constraints[0]
    assert c.rhs == Decimal("-50")


# ---------------------------------------------------------------------------
# Multiple arcs / instruments
# ---------------------------------------------------------------------------


def test_multiple_arcs_emits_one_constraint_per_arc():
    arcs_f = [
        _make_arc("A", "B", Decimal("100"), period=_PERIOD_FROM),
        _make_arc("C", "D", Decimal("200"), period=_PERIOD_FROM),
    ]
    arcs_t = [
        _make_arc("A", "B", Decimal("110"), period=_PERIOD_TO),
        _make_arc("C", "D", Decimal("230"), period=_PERIOD_TO),
    ]
    flow_terms: FlowTerms = {
        ("A", "B", "A3"): Decimal("10"),
        ("C", "D", "A3"): Decimal("30"),
    }
    cs = build_flow_funds_rows(
        arcs_f, arcs_t,
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms=flow_terms,
    )
    assert len(cs.constraints) == 2


def test_multiple_instruments_separate_constraints():
    arc_f_a3 = _make_arc("A", "B", Decimal("100"), cls=ArcClass.A3, period=_PERIOD_FROM)
    arc_f_a4 = _make_arc("A", "B", Decimal("200"), cls=ArcClass.A4, period=_PERIOD_FROM)
    arc_t_a3 = _make_arc("A", "B", Decimal("110"), cls=ArcClass.A3, period=_PERIOD_TO)
    arc_t_a4 = _make_arc("A", "B", Decimal("220"), cls=ArcClass.A4, period=_PERIOD_TO)
    flow_terms: FlowTerms = {
        ("A", "B", "A3"): Decimal("10"),
        ("A", "B", "A4"): Decimal("20"),
    }
    cs = build_flow_funds_rows(
        [arc_f_a3, arc_f_a4], [arc_t_a3, arc_t_a4],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms=flow_terms,
    )
    assert len(cs.constraints) == 2
    instrs = {c.provenance.split("instrument '")[1].split("'")[0] for c in cs.constraints}
    assert instrs == {"A3", "A4"}


def test_constraints_sorted_by_flow_key():
    """Constraints are emitted in sorted(flow_terms) order."""
    flow_terms: FlowTerms = {
        ("Z", "Z", "A3"): Decimal("1"),
        ("A", "A", "A3"): Decimal("2"),
        ("M", "M", "A3"): Decimal("3"),
    }
    cs = build_flow_funds_rows(
        [], [],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms=flow_terms,
    )
    provenance_arcs = [
        _provenance_arc(c.provenance) for c in cs.constraints
    ]
    srcs = [p[0] for p in provenance_arcs if p]
    assert srcs == sorted(srcs)


# ---------------------------------------------------------------------------
# Period filtering
# ---------------------------------------------------------------------------


def test_facts_with_wrong_period_are_ignored():
    """Facts for a period other than period_from/period_to are filtered out."""
    arc_wrong_period = _make_arc("A", "B", Decimal("999"), period=_OTHER_PERIOD)
    arc_correct = _make_arc("A", "B", Decimal("100"), period=_PERIOD_FROM)

    cs = build_flow_funds_rows(
        [arc_wrong_period, arc_correct], [],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("A", "B", "A3"): Decimal("50")},
    )
    c = cs.constraints[0]
    # Only arc_correct should contribute; arc_wrong_period has x(t)=100 after filter.
    key_from: ArcKey = ("A", "B", "A3", str(_PERIOD_FROM))
    assert key_from in c.matrix_row
    assert c.matrix_row[key_from] == Decimal("-1")


# ---------------------------------------------------------------------------
# check_flow_funds — satisfied network
# ---------------------------------------------------------------------------


def test_check_flow_funds_satisfied_no_violations():
    amount_from = Decimal("1000")
    F = Decimal("100")
    R = Decimal("50")
    amount_to = amount_from + F + R

    net_f = _make_network([_make_arc("A", "B", amount_from, period=_PERIOD_FROM)], _PERIOD_FROM)
    net_t = _make_network([_make_arc("A", "B", amount_to, period=_PERIOD_TO)], _PERIOD_TO)

    result = check_flow_funds(
        net_f, net_t,
        flow_terms={("A", "B", "A3"): F},
        revaluation_terms={("A", "B", "A3"): R},
    )
    assert result.satisfied is True
    assert result.violations == []
    assert result.checked_count == 1


def test_check_flow_funds_periods_recorded_correctly():
    net_f = _empty_network(_PERIOD_FROM)
    net_t = _empty_network(_PERIOD_TO)
    result = check_flow_funds(net_f, net_t, flow_terms={})
    assert result.period_from == _PERIOD_FROM
    assert result.period_to == _PERIOD_TO


# ---------------------------------------------------------------------------
# check_flow_funds — violation detection
# ---------------------------------------------------------------------------


def test_check_flow_funds_detects_violation():
    amount_from = Decimal("1000")
    F = Decimal("100")
    # amount_to doesn't match F: difference of 500 >> tolerance
    amount_to = amount_from + F + Decimal("500")

    net_f = _make_network([_make_arc("A", "B", amount_from, period=_PERIOD_FROM)], _PERIOD_FROM)
    net_t = _make_network([_make_arc("A", "B", amount_to, period=_PERIOD_TO)], _PERIOD_TO)

    result = check_flow_funds(
        net_f, net_t,
        flow_terms={("A", "B", "A3"): F},
    )
    assert result.satisfied is False
    assert len(result.violations) == 1
    v = result.violations[0]
    assert v.source_node_id == "A"
    assert v.target_node_id == "B"
    assert v.instrument_class_value == "A3"
    assert v.residual == Decimal("500")


def test_check_flow_funds_violation_has_correct_fields():
    amount_from = Decimal("500")
    f_term = Decimal("100")
    r_term = Decimal("25")
    # Make a bad amount_to so violation is triggered.
    amount_to = amount_from + f_term + r_term + Decimal("1000")

    net_f = _make_network([_make_arc("X", "Y", amount_from, period=_PERIOD_FROM)], _PERIOD_FROM)
    net_t = _make_network([_make_arc("X", "Y", amount_to, period=_PERIOD_TO)], _PERIOD_TO)

    result = check_flow_funds(
        net_f, net_t,
        flow_terms={("X", "Y", "A3"): f_term},
        revaluation_terms={("X", "Y", "A3"): r_term},
    )
    v = result.violations[0]
    assert v.amount_from == amount_from
    assert v.amount_to == amount_to
    assert v.flow_term == f_term
    assert v.revaluation_term == r_term
    assert v.expected_change == f_term + r_term
    assert v.actual_change == amount_to - amount_from
    assert v.residual == (amount_to - amount_from) - (f_term + r_term)


def test_check_flow_funds_within_tolerance_no_violation():
    """Residual within relative tolerance → no violation."""
    F = Decimal("100")
    amount_from = Decimal("1000")
    # Make residual < 0.001 * |F| = 0.1, well within the absolute floor of 0.1
    # Shift by just 0.05 (below floor of 0.1).
    amount_to = amount_from + F + Decimal("0.05")

    net_f = _make_network([_make_arc("A", "B", amount_from, period=_PERIOD_FROM)], _PERIOD_FROM)
    net_t = _make_network([_make_arc("A", "B", amount_to, period=_PERIOD_TO)], _PERIOD_TO)

    result = check_flow_funds(
        net_f, net_t,
        flow_terms={("A", "B", "A3"): F},
    )
    assert result.satisfied is True


def test_check_flow_funds_just_above_absolute_floor_triggers_violation():
    """Residual just above _MIN_ABS_TOL triggers a violation."""
    F = Decimal("0")  # zero flow → threshold = max(0, 0.1) = 0.1
    amount_from = Decimal("1000")
    amount_to = amount_from + Decimal("0.11")  # residual 0.11 > 0.1

    net_f = _make_network([_make_arc("A", "B", amount_from, period=_PERIOD_FROM)], _PERIOD_FROM)
    net_t = _make_network([_make_arc("A", "B", amount_to, period=_PERIOD_TO)], _PERIOD_TO)

    result = check_flow_funds(
        net_f, net_t,
        flow_terms={("A", "B", "A3"): F},
    )
    assert not result.satisfied
    assert len(result.violations) == 1


# ---------------------------------------------------------------------------
# check_flow_funds — arc_count vs checked_count
# ---------------------------------------------------------------------------


def test_check_flow_funds_arc_count_is_union_of_both_networks():
    """arc_count = distinct arcs in union of both networks (not just flow_terms)."""
    net_f = _make_network([
        _make_arc("A", "B", Decimal("100"), period=_PERIOD_FROM),
        _make_arc("C", "D", Decimal("200"), period=_PERIOD_FROM),
    ], _PERIOD_FROM)
    net_t = _make_network([
        _make_arc("A", "B", Decimal("120"), period=_PERIOD_TO),
        _make_arc("E", "F", Decimal("50"), period=_PERIOD_TO),
    ], _PERIOD_TO)

    result = check_flow_funds(
        net_f, net_t,
        flow_terms={("A", "B", "A3"): Decimal("20")},
    )
    # Arcs across both networks: (A,B,A3), (C,D,A3), (E,F,A3) = 3
    assert result.arc_count == 3
    # Only (A,B,A3) has a flow term
    assert result.checked_count == 1


def test_check_flow_funds_checked_count_equals_flow_terms_len():
    net_f = _make_network([
        _make_arc("A", "B", Decimal("100"), period=_PERIOD_FROM),
        _make_arc("C", "D", Decimal("200"), period=_PERIOD_FROM),
    ], _PERIOD_FROM)
    net_t = _make_network([
        _make_arc("A", "B", Decimal("110"), period=_PERIOD_TO),
        _make_arc("C", "D", Decimal("220"), period=_PERIOD_TO),
    ], _PERIOD_TO)

    flow_terms: FlowTerms = {
        ("A", "B", "A3"): Decimal("10"),
        ("C", "D", "A3"): Decimal("20"),
    }
    result = check_flow_funds(net_f, net_t, flow_terms=flow_terms)
    assert result.checked_count == 2


# ---------------------------------------------------------------------------
# Provenance format
# ---------------------------------------------------------------------------


def test_provenance_format_contains_expected_fields():
    arc_f = _make_arc("src_node", "tgt_node", Decimal("100"), period=_PERIOD_FROM)
    arc_t = _make_arc("src_node", "tgt_node", Decimal("110"), period=_PERIOD_TO)
    cs = build_flow_funds_rows(
        [arc_f], [arc_t],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("src_node", "tgt_node", "A3"): Decimal("10")},
    )
    prov = cs.constraints[0].provenance
    assert "src_node" in prov
    assert "tgt_node" in prov
    assert "A3" in prov
    assert str(_PERIOD_FROM) in prov
    assert str(_PERIOD_TO) in prov
    assert "Law 4" in prov


def test_check_flow_funds_provenance_contains_amounts():
    amount_from = Decimal("800")
    f_term = Decimal("100")
    r_term = Decimal("20")
    # Bad amount_to to trigger violation.
    amount_to = amount_from + f_term + r_term + Decimal("500")

    net_f = _make_network([_make_arc("A", "B", amount_from, period=_PERIOD_FROM)], _PERIOD_FROM)
    net_t = _make_network([_make_arc("A", "B", amount_to, period=_PERIOD_TO)], _PERIOD_TO)

    result = check_flow_funds(
        net_f, net_t,
        flow_terms={("A", "B", "A3"): f_term},
        revaluation_terms={("A", "B", "A3"): r_term},
    )
    v = result.violations[0]
    assert str(amount_from) in v.provenance
    assert str(amount_to) in v.provenance
    assert str(f_term) in v.provenance
    assert str(r_term) in v.provenance


def test_provenance_arc_valid_string():
    prov = (
        "Law 4 (flow-of-funds) for arc 'node_a' -> 'node_b' "
        "instrument 'A3', period '2024-Q3' -> '2024-Q4'"
    )
    result = _provenance_arc(prov)
    assert result is not None
    src, tgt, instr, p_from, p_to = result
    assert src == "node_a"
    assert tgt == "node_b"
    assert instr == "A3"
    assert p_from == "2024-Q3"
    assert p_to == "2024-Q4"


def test_provenance_arc_invalid_string_returns_none():
    assert _provenance_arc("not a valid provenance") is None
    assert _provenance_arc("") is None
    assert _provenance_arc("Law 3 (sectoral) for sector 'X'") is None


# ---------------------------------------------------------------------------
# Non-adjacent periods (should still work)
# ---------------------------------------------------------------------------


def test_non_adjacent_periods_still_works():
    """Law 4 can be applied across non-adjacent periods (unusual but valid)."""
    period_early = Period("2020-Q1")
    period_late = Period("2024-Q4")

    arc_f = _make_arc("A", "B", Decimal("1000"), period=period_early)
    arc_t = _make_arc("A", "B", Decimal("1500"), period=period_late)
    F = Decimal("500")

    cs = build_flow_funds_rows(
        [arc_f], [arc_t],
        period_from=period_early,
        period_to=period_late,
        flow_terms={("A", "B", "A3"): F},
    )
    assert len(cs.constraints) == 1
    c = cs.constraints[0]
    assert str(period_early) in c.provenance
    assert str(period_late) in c.provenance


# ---------------------------------------------------------------------------
# Decimal precision
# ---------------------------------------------------------------------------


def test_decimal_precision_preserved_in_rhs():
    """High-precision Decimal values are not rounded in constraint RHS."""
    F = Decimal("123.456789")
    R = Decimal("0.001234")
    arc_f = _make_arc("A", "B", Decimal("1000.00"), period=_PERIOD_FROM)
    arc_t = _make_arc("A", "B", Decimal("1123.458023"), period=_PERIOD_TO)

    cs = build_flow_funds_rows(
        [arc_f], [arc_t],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("A", "B", "A3"): F},
        revaluation_terms={("A", "B", "A3"): R},
    )
    c = cs.constraints[0]
    # rhs = F + R = 123.456789 + 0.001234 = 123.458023
    assert c.rhs == Decimal("123.458023")


# ---------------------------------------------------------------------------
# ArcKey format
# ---------------------------------------------------------------------------


def test_arc_key_format_includes_period_string():
    """ArcKey 4-tuple has period string in position [3]."""
    arc_f = _make_arc("A", "B", Decimal("100"), period=_PERIOD_FROM)
    arc_t = _make_arc("A", "B", Decimal("150"), period=_PERIOD_TO)
    cs = build_flow_funds_rows(
        [arc_f], [arc_t],
        period_from=_PERIOD_FROM,
        period_to=_PERIOD_TO,
        flow_terms={("A", "B", "A3"): Decimal("50")},
    )
    c = cs.constraints[0]
    for key in c.matrix_row:
        src, tgt, instr, period_str = key
        assert period_str in {str(_PERIOD_FROM), str(_PERIOD_TO)}
        assert src == "A"
        assert tgt == "B"
        assert instr == "A3"
