"""Property-based and unit tests for claimweb.constraints.kcl (Law 1).

Tests verify four properties per the constraint-author skill:
1. Soundness    — on a network satisfying Law 1 by construction, build_kcl_rows
                  emits constraints that are all satisfied.
2. Completeness — on a network violating Law 1 (one arc perturbed), check_kcl
                  detects at least one violation.
3. Stability    — perturbing a DIRECT_MEASURED arc by δ shifts the constraint
                  RHS by exactly ±δ (linear; no chaotic behaviour).
4. Independence — each constraint's matrix_row only references arcs incident to
                  the constraint's own node.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from claimweb.constraints.kcl import (
    ArcKey,
    ConstraintSet,
    KCLResult,
    KCLViolation,
    LinearConstraint,
    NetworkState,
    NodeBalance,
    _MIN_ABS_TOL,
    _provenance_node,
    build_kcl_rows,
    check_kcl,
)
from claimweb.fetchers.base import ArcClass, ArcFact, DataQualityFlag, Period

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_DUMMY_SHA256 = "a" * 64
_PERIOD = Period("2024-Q4")


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


def _balance(
    node_id: str,
    equity: Decimal,
    nonfinancial: Decimal = Decimal("0"),
    period: Period = _PERIOD,
) -> NodeBalance:
    return NodeBalance(
        node_id=node_id,
        period=period,
        equity_millions=equity,
        nonfinancial_assets_millions=nonfinancial,
    )


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

_large_perturbation = st.decimals(
    min_value=Decimal("1000"),   # well above _MIN_ABS_TOL and any 0.01 % threshold
    max_value=Decimal("500000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def valid_network(draw: st.DrawFn) -> NetworkState:
    """NetworkState that satisfies Law 1 at every node by construction.

    Strategy:
    * Pick 2–4 node IDs.
    * Pick 1–6 random arcs (no self-loops, unique source-target pairs).
    * Set equity = outgoing_total - incoming_total for each node (N=0),
      ensuring Law 1 holds exactly.
    """
    n_nodes: int = draw(st.integers(min_value=2, max_value=4))
    node_ids = [f"node_{i}" for i in range(n_nodes)]

    all_pairs = [(s, t) for s in node_ids for t in node_ids if s != t]
    n_arcs = draw(st.integers(min_value=1, max_value=min(6, len(all_pairs))))
    pairs = draw(
        st.lists(
            st.sampled_from(all_pairs),
            min_size=n_arcs,
            max_size=n_arcs,
            unique=True,
        )
    )

    out_sum: dict[str, Decimal] = {nid: Decimal("0") for nid in node_ids}
    in_sum: dict[str, Decimal] = {nid: Decimal("0") for nid in node_ids}
    arcs: list[ArcFact] = []

    for src, tgt in pairs:
        amount: Decimal = draw(_amounts)
        arcs.append(_make_arc(src, tgt, amount))
        out_sum[src] += amount
        in_sum[tgt] += amount

    # Equity = outgoing − incoming; Law 1 is satisfied with N_i = 0.
    node_balances = {
        nid: _balance(nid, out_sum[nid] - in_sum[nid])
        for nid in node_ids
    }

    return NetworkState(period=_PERIOD, arcs=arcs, node_balances=node_balances)


# ---------------------------------------------------------------------------
# Property 1 — Soundness
# ---------------------------------------------------------------------------


@given(valid_network())
@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
def test_soundness_build_kcl_rows(network: NetworkState) -> None:
    """On a Law-1-satisfying network, every compiled constraint is satisfied.

    Substitutes the network's true arc values into each LinearConstraint's
    matrix_row and asserts that LHS == RHS to within Decimal tolerance.
    """
    cs: ConstraintSet = build_kcl_rows(network)

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


@given(valid_network())
@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
def test_soundness_check_kcl(network: NetworkState) -> None:
    """check_kcl reports satisfied=True on a Law-1-satisfying network."""
    result: KCLResult = check_kcl(network, tol=Decimal("0.0001"))
    assert result.satisfied, (
        f"Expected satisfied network but got violations:\n"
        + "\n".join(f"  {v.provenance}" for v in result.violations)
    )
    assert result.node_count >= 1
    assert result.checked_count == result.node_count


# ---------------------------------------------------------------------------
# Property 2 — Completeness
# ---------------------------------------------------------------------------


@given(valid_network(), _large_perturbation)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_completeness_check_kcl(network: NetworkState, extra: Decimal) -> None:
    """Perturbing one arc amount by a large value causes check_kcl to report a violation.

    The extra amount is chosen to be well above the tolerance threshold so the
    violation is always detected, regardless of the network's total assets.
    """
    orig = network.arcs[0]
    perturbed_arc = _make_arc(
        orig.source_node_id,
        orig.target_node_id,
        orig.dollar_amount_millions + extra,
    )
    bad_network = NetworkState(
        period=network.period,
        arcs=[perturbed_arc] + network.arcs[1:],
        node_balances=network.node_balances,
    )

    result: KCLResult = check_kcl(bad_network, tol=Decimal("0.0001"))
    assert not result.satisfied, (
        f"Expected violation after perturbing arc by {extra} but got satisfied"
    )
    assert len(result.violations) >= 1

    # The source or target of the perturbed arc must be in the violation set.
    violating_nodes = {v.node_id for v in result.violations}
    assert (
        orig.source_node_id in violating_nodes
        or orig.target_node_id in violating_nodes
    ), (
        f"Expected source {orig.source_node_id!r} or target "
        f"{orig.target_node_id!r} in violations, got {violating_nodes}"
    )


# ---------------------------------------------------------------------------
# Property 3 — Stability
# ---------------------------------------------------------------------------


@given(valid_network(), _amounts, _amounts)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_stability_build_kcl_rows(
    network: NetworkState,
    direct_amount: Decimal,
    delta: Decimal,
) -> None:
    """Perturbing a DIRECT_MEASURED arc by δ shifts its nodes' RHS by exactly ±δ.

    The coefficient matrix is always ±1 for KCL (independent of arc values).
    For a DIRECT_MEASURED arc A→B, perturbing the amount by δ must:
    * Shift node A's constraint RHS by -δ (outgoing measured arc reduces RHS).
    * Shift node B's constraint RHS by +δ (incoming measured arc increases RHS).
    * Leave all other nodes' RHS unchanged.
    """
    orig = network.arcs[0]
    src = orig.source_node_id
    tgt = orig.target_node_id

    def _with_direct(amount: Decimal) -> NetworkState:
        direct_arc = _make_arc(src, tgt, amount, flag=DataQualityFlag.DIRECT_MEASURED)
        remaining = [a for a in network.arcs if a is not orig]
        return NetworkState(
            period=network.period,
            arcs=[direct_arc] + remaining,
            node_balances=network.node_balances,
        )

    cs1 = build_kcl_rows(_with_direct(direct_amount))
    cs2 = build_kcl_rows(_with_direct(direct_amount + delta))

    # Both ConstraintSets must cover the same set of nodes in the same order.
    assert len(cs1.constraints) == len(cs2.constraints)

    for c1, c2 in zip(cs1.constraints, cs2.constraints):
        assert c1.provenance == c2.provenance, "Provenance ordering changed"
        node_id = _provenance_node(c1.provenance)

        if node_id == src:
            expected_shift = -delta
        elif node_id == tgt:
            expected_shift = delta
        else:
            expected_shift = Decimal("0")

        actual_shift = c2.rhs - c1.rhs
        assert actual_shift == expected_shift, (
            f"Stability failure for node {node_id!r}: "
            f"expected RHS shift {expected_shift}, got {actual_shift}"
        )


# ---------------------------------------------------------------------------
# Property 4 — Independence
# ---------------------------------------------------------------------------


@given(valid_network())
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_independence_build_kcl_rows(network: NetworkState) -> None:
    """Each constraint's matrix_row only references arcs incident to its node.

    KCL constraints for different nodes must not entangle: the variables in
    node i's constraint must all have node i as either source or target.
    """
    cs: ConstraintSet = build_kcl_rows(network)

    seen_nodes: set[str] = set()
    for c in cs.constraints:
        node_id = _provenance_node(c.provenance)
        assert node_id is not None, f"Cannot parse node from provenance: {c.provenance!r}"
        assert node_id not in seen_nodes, (
            f"Duplicate constraint for node {node_id!r}"
        )
        seen_nodes.add(node_id)

        for arc_key in c.matrix_row:
            arc_src, arc_tgt, _, _ = arc_key
            assert arc_src == node_id or arc_tgt == node_id, (
                f"Independence failure: constraint for node {node_id!r} "
                f"references arc {arc_src!r}→{arc_tgt!r}"
            )


# ---------------------------------------------------------------------------
# Unit tests — build_kcl_rows
# ---------------------------------------------------------------------------


class TestBuildKclRows:
    def test_empty_network_no_arcs_no_balances(self) -> None:
        """Network with no arcs and no balances produces an empty ConstraintSet."""
        network = NetworkState(period=_PERIOD, arcs=[], node_balances={})
        cs = build_kcl_rows(network)
        assert cs.constraints == []
        assert cs.unknowns == []

    def test_node_in_balances_only_no_arcs(self) -> None:
        """A node with a balance entry but no arcs gets one constraint with empty row."""
        network = NetworkState(
            period=_PERIOD,
            arcs=[],
            node_balances={"A": _balance("A", Decimal("50"))},
        )
        cs = build_kcl_rows(network)
        assert len(cs.constraints) == 1
        c = cs.constraints[0]
        assert c.kind == "eq"
        assert c.matrix_row == {}
        # RHS = E_A - N_A = 50 - 0 = 50
        assert c.rhs == Decimal("50")
        assert "node 'A'" in c.provenance

    def test_single_arc_both_nodes_get_constraints(self) -> None:
        """One arc A→B yields two constraints (one per node)."""
        arcs = [_make_arc("A", "B", Decimal("100"))]
        network = NetworkState(
            period=_PERIOD,
            arcs=arcs,
            node_balances={
                "A": _balance("A", Decimal("100")),
                "B": _balance("B", Decimal("-100")),
            },
        )
        cs = build_kcl_rows(network)
        assert len(cs.constraints) == 2

        # Constraints are sorted by node_id, so A first, then B.
        c_a, c_b = cs.constraints
        assert _provenance_node(c_a.provenance) == "A"
        assert _provenance_node(c_b.provenance) == "B"

        # Arc key for A→B
        key: ArcKey = ("A", "B", ArcClass.A3.value, str(_PERIOD))
        assert c_a.matrix_row.get(key) == Decimal("1")   # outgoing → +1
        assert c_b.matrix_row.get(key) == Decimal("-1")  # incoming → -1

        # RHS_A = E_A - N_A = 100 - 0 = 100
        assert c_a.rhs == Decimal("100")
        # RHS_B = E_B - N_B = -100 - 0 = -100
        assert c_b.rhs == Decimal("-100")

    def test_direct_measured_arc_folds_into_rhs(self) -> None:
        """A DIRECT_MEASURED arc does not appear in matrix_row; its amount shifts RHS."""
        arcs = [_make_arc("A", "B", Decimal("500"), flag=DataQualityFlag.DIRECT_MEASURED)]
        network = NetworkState(
            period=_PERIOD,
            arcs=arcs,
            node_balances={
                "A": _balance("A", Decimal("200")),
                "B": _balance("B", Decimal("0")),
            },
        )
        cs = build_kcl_rows(network)
        key: ArcKey = ("A", "B", ArcClass.A3.value, str(_PERIOD))

        c_a = next(c for c in cs.constraints if _provenance_node(c.provenance) == "A")
        c_b = next(c for c in cs.constraints if _provenance_node(c.provenance) == "B")

        # Direct arc must not appear as a variable.
        assert key not in c_a.matrix_row
        assert key not in c_b.matrix_row

        # RHS_A = E_A - N_A - amount_out = 200 - 0 - 500 = -300
        assert c_a.rhs == Decimal("-300")
        # RHS_B = E_B - N_B + amount_in = 0 - 0 + 500 = 500
        assert c_b.rhs == Decimal("500")

    def test_mixed_direct_and_unknown_arcs(self) -> None:
        """Only unknown arcs appear in matrix_row; direct arcs adjust RHS only."""
        direct_arc = _make_arc(
            "A", "B", Decimal("300"), flag=DataQualityFlag.DIRECT_MEASURED
        )
        unknown_arc = _make_arc(
            "B", "C", Decimal("150"), flag=DataQualityFlag.MARGINAL_INFERRED
        )
        network = NetworkState(
            period=_PERIOD,
            arcs=[direct_arc, unknown_arc],
            node_balances={
                "A": _balance("A", Decimal("0")),
                "B": _balance("B", Decimal("0")),
                "C": _balance("C", Decimal("0")),
            },
        )
        cs = build_kcl_rows(network)

        direct_key: ArcKey = ("A", "B", ArcClass.A3.value, str(_PERIOD))
        unknown_key: ArcKey = ("B", "C", ArcClass.A3.value, str(_PERIOD))

        c_b = next(c for c in cs.constraints if _provenance_node(c.provenance) == "B")
        assert direct_key not in c_b.matrix_row  # folded into RHS
        assert c_b.matrix_row.get(unknown_key) == Decimal("1")  # outgoing unknown
        # RHS_B = E_B - N_B + direct_in = 0 - 0 + 300 = 300
        assert c_b.rhs == Decimal("300")

    def test_nonfinancial_assets_reduce_rhs(self) -> None:
        """Non-financial assets (N_i) are subtracted from the RHS of node i's constraint."""
        arcs = [_make_arc("A", "B", Decimal("400"))]
        network = NetworkState(
            period=_PERIOD,
            arcs=arcs,
            node_balances={"A": _balance("A", Decimal("500"), nonfinancial=Decimal("100"))},
        )
        cs = build_kcl_rows(network)
        c_a = next(c for c in cs.constraints if _provenance_node(c.provenance) == "A")
        # RHS = E_A - N_A = 500 - 100 = 400
        assert c_a.rhs == Decimal("400")

    def test_multiple_instrument_classes(self) -> None:
        """Arcs of different ArcClass values produce distinct ArcKeys."""
        arc_a3 = _make_arc("X", "Y", Decimal("100"), cls=ArcClass.A3)
        arc_a1 = _make_arc("X", "Y", Decimal("200"), cls=ArcClass.A1)
        network = NetworkState(
            period=_PERIOD,
            arcs=[arc_a3, arc_a1],
            node_balances={"X": _balance("X", Decimal("300")), "Y": _balance("Y", Decimal("-300"))},
        )
        cs = build_kcl_rows(network)
        c_x = next(c for c in cs.constraints if _provenance_node(c.provenance) == "X")
        key_a3: ArcKey = ("X", "Y", ArcClass.A3.value, str(_PERIOD))
        key_a1: ArcKey = ("X", "Y", ArcClass.A1.value, str(_PERIOD))
        assert c_x.matrix_row.get(key_a3) == Decimal("1")
        assert c_x.matrix_row.get(key_a1) == Decimal("1")

    def test_duplicate_arcs_are_summed(self) -> None:
        """Two ArcFacts with the same key are aggregated before constraints are built."""
        arc1 = _make_arc("A", "B", Decimal("100"))
        arc2 = _make_arc("A", "B", Decimal("50"))
        network = NetworkState(
            period=_PERIOD,
            arcs=[arc1, arc2],
            node_balances={
                "A": _balance("A", Decimal("150")),
                "B": _balance("B", Decimal("-150")),
            },
        )
        # Should behave exactly like a single arc with amount=150.
        cs = build_kcl_rows(network)
        assert len(cs.constraints) == 2
        c_a = next(c for c in cs.constraints if _provenance_node(c.provenance) == "A")
        # One variable for the combined arc.
        assert len(c_a.matrix_row) == 1

    def test_unknowns_list_sorted(self) -> None:
        """The unknowns list is sorted deterministically."""
        arcs = [
            _make_arc("B", "A", Decimal("10")),
            _make_arc("A", "C", Decimal("20")),
        ]
        network = NetworkState(
            period=_PERIOD,
            arcs=arcs,
            node_balances={
                "A": _balance("A", Decimal("10")),
                "B": _balance("B", Decimal("10")),
                "C": _balance("C", Decimal("-20")),
            },
        )
        cs = build_kcl_rows(network)
        assert cs.unknowns == sorted(cs.unknowns)

    def test_provenance_contains_period(self) -> None:
        """Each constraint's provenance string contains the period."""
        period = Period("2020-Q1")
        arcs = [_make_arc("A", "B", Decimal("1"), period=period)]
        network = NetworkState(
            period=period,
            arcs=arcs,
            node_balances={
                "A": _balance("A", Decimal("1"), period=period),
                "B": _balance("B", Decimal("-1"), period=period),
            },
        )
        cs = build_kcl_rows(network)
        for c in cs.constraints:
            assert "2020-Q1" in c.provenance

    def test_constraint_kind_is_eq(self) -> None:
        """All KCL constraints are equality constraints."""
        arcs = [_make_arc("A", "B", Decimal("500"))]
        network = NetworkState(
            period=_PERIOD,
            arcs=arcs,
            node_balances={
                "A": _balance("A", Decimal("500")),
                "B": _balance("B", Decimal("-500")),
            },
        )
        cs = build_kcl_rows(network)
        for c in cs.constraints:
            assert c.kind == "eq"

    def test_node_not_in_balances_gets_zero_equity(self) -> None:
        """A node appearing only in arcs (not in node_balances) uses E=0, N=0."""
        arcs = [_make_arc("ghost", "B", Decimal("300"))]
        network = NetworkState(
            period=_PERIOD,
            arcs=arcs,
            node_balances={"B": _balance("B", Decimal("-300"))},
        )
        cs = build_kcl_rows(network)
        c_ghost = next(c for c in cs.constraints if _provenance_node(c.provenance) == "ghost")
        # RHS = E_ghost - N_ghost = 0 - 0 = 0
        assert c_ghost.rhs == Decimal("0")


# ---------------------------------------------------------------------------
# Unit tests — check_kcl
# ---------------------------------------------------------------------------


class TestCheckKcl:
    def test_empty_network_is_satisfied(self) -> None:
        """An empty network trivially satisfies Law 1."""
        network = NetworkState(period=_PERIOD, arcs=[], node_balances={})
        result = check_kcl(network)
        assert result.satisfied
        assert result.violations == []
        assert result.node_count == 0
        assert result.checked_count == 0

    def test_single_arc_satisfied(self) -> None:
        """A two-node network with correct equity is satisfied."""
        arcs = [_make_arc("A", "B", Decimal("200"))]
        network = NetworkState(
            period=_PERIOD,
            arcs=arcs,
            node_balances={
                "A": _balance("A", Decimal("200")),  # E_A = 200 = outgoing
                "B": _balance("B", Decimal("-200")),  # E_B = -200 = -incoming
            },
        )
        result = check_kcl(network)
        assert result.satisfied
        assert result.node_count == 2

    def test_single_arc_violated(self) -> None:
        """Wrong equity at node A produces exactly one violation."""
        arcs = [_make_arc("A", "B", Decimal("200"))]
        network = NetworkState(
            period=_PERIOD,
            arcs=arcs,
            node_balances={
                "A": _balance("A", Decimal("100")),  # wrong: should be 200
                "B": _balance("B", Decimal("-200")),
            },
        )
        result = check_kcl(network)
        assert not result.satisfied
        assert len(result.violations) == 1
        v = result.violations[0]
        assert v.node_id == "A"
        assert v.residual == Decimal("100")  # 200 - 0 - 100

    def test_three_node_cycle_satisfied(self) -> None:
        """A→B→C→A cycle with correct equity satisfies Law 1 at all nodes."""
        arcs = [
            _make_arc("A", "B", Decimal("100")),
            _make_arc("B", "C", Decimal("100")),
            _make_arc("C", "A", Decimal("100")),
        ]
        # Each node: outgoing=100, incoming=100 → equity=0
        node_balances = {
            nid: _balance(nid, Decimal("0")) for nid in ("A", "B", "C")
        }
        network = NetworkState(period=_PERIOD, arcs=arcs, node_balances=node_balances)
        result = check_kcl(network)
        assert result.satisfied
        assert result.node_count == 3

    def test_violation_residual_sign(self) -> None:
        """Residual sign is correct: positive when assets exceed liabilities+equity."""
        arcs = [_make_arc("A", "B", Decimal("1000"))]
        network = NetworkState(
            period=_PERIOD,
            arcs=arcs,
            node_balances={"A": _balance("A", Decimal("0"))},  # E=0, should be 1000
        )
        result = check_kcl(network)
        assert not result.satisfied
        v = next(v for v in result.violations if v.node_id == "A")
        assert v.residual > Decimal("0")  # assets > liabilities + equity

    def test_nonfinancial_assets_included_in_check(self) -> None:
        """Non-financial assets contribute to asset_sum; omitting them produces a violation."""
        arcs = [_make_arc("A", "B", Decimal("500"))]
        # Correct: E_A = 600, N_A = 100 → assets_A = 500+100 = 600 = E_A ✓
        #          E_B = -500, N_B = 0 → assets_B = 0; liabs_B = 500 → residual=0 ✓
        network_ok = NetworkState(
            period=_PERIOD,
            arcs=arcs,
            node_balances={
                "A": _balance("A", Decimal("600"), nonfinancial=Decimal("100")),
                "B": _balance("B", Decimal("-500")),
            },
        )
        assert check_kcl(network_ok).satisfied

        # Wrong: E_A = 600, N_A = 0 → assets_A = 500 ≠ 600 → violation at A
        network_bad = NetworkState(
            period=_PERIOD,
            arcs=arcs,
            node_balances={
                "A": _balance("A", Decimal("600"), nonfinancial=Decimal("0")),
                "B": _balance("B", Decimal("-500")),
            },
        )
        result_bad = check_kcl(network_bad)
        assert not result_bad.satisfied
        assert any(v.node_id == "A" for v in result_bad.violations)

    def test_tolerance_respected(self) -> None:
        """Tiny residuals within the absolute floor do not produce violations."""
        # residual at A = 1000.005 - 0 - 1000 = 0.005 < _MIN_ABS_TOL (0.01) → no violation
        # Node B is balanced exactly.
        arcs = [_make_arc("A", "B", Decimal("1000.005"))]
        network = NetworkState(
            period=_PERIOD,
            arcs=arcs,
            node_balances={
                "A": _balance("A", Decimal("1000")),
                "B": _balance("B", Decimal("-1000.005")),
            },
        )
        result = check_kcl(network, tol=Decimal("0"))
        assert result.satisfied

    def test_tolerance_exceeded(self) -> None:
        """A residual above the tolerance floor produces a violation."""
        arcs = [_make_arc("A", "B", Decimal("1000"))]
        network = NetworkState(
            period=_PERIOD,
            arcs=arcs,
            node_balances={
                "A": _balance("A", Decimal("980")),    # residual = 20
                "B": _balance("B", Decimal("-1000")),  # balanced
            },
        )
        # 20 > _MIN_ABS_TOL (0.01) and > 0.0001 * 1000 = 0.1
        result = check_kcl(network)
        assert not result.satisfied
        assert any(v.node_id == "A" for v in result.violations)

    def test_violation_carries_full_diagnostic(self) -> None:
        """KCLViolation records asset_sum, liab_sum, equity, residual, provenance."""
        arcs = [_make_arc("A", "B", Decimal("300"))]
        network = NetworkState(
            period=_PERIOD,
            arcs=arcs,
            node_balances={
                "A": _balance("A", Decimal("100"), nonfinancial=Decimal("50")),
                "B": _balance("B", Decimal("-300")),
            },
        )
        result = check_kcl(network)
        # Node A: assets = 300 + 50 = 350, liabs = 0, equity = 100
        # residual = 350 - 0 - 100 = 250 → violation
        v_a = next((v for v in result.violations if v.node_id == "A"), None)
        assert v_a is not None
        assert v_a.asset_sum == Decimal("350")
        assert v_a.liab_sum == Decimal("0")
        assert v_a.equity == Decimal("100")
        assert v_a.nonfinancial == Decimal("50")
        assert v_a.residual == Decimal("250")
        assert "A" in v_a.provenance
        assert "2024-Q4" in v_a.provenance

    def test_result_period_matches_network(self) -> None:
        """KCLResult.period matches the network's period."""
        period = Period("2007-Q3")
        network = NetworkState(
            period=period,
            arcs=[],
            node_balances={"A": _balance("A", Decimal("0"), period=period)},
        )
        result = check_kcl(network)
        assert result.period == period

    def test_node_absent_from_balances_uses_zero_equity(self) -> None:
        """Ghost nodes (in arcs only) have E=0 and N=0; large arcs still violate."""
        # ghost has 5000 outgoing but no equity → residual=5000 → violation
        arcs = [_make_arc("ghost", "B", Decimal("5000"))]
        network = NetworkState(period=_PERIOD, arcs=arcs, node_balances={})
        result = check_kcl(network)
        assert not result.satisfied
        ghost_v = next(v for v in result.violations if v.node_id == "ghost")
        assert ghost_v.residual == Decimal("5000")

    def test_multiple_arcs_same_pair_summed(self) -> None:
        """Duplicate ArcFacts (same key) are summed before verification."""
        arc1 = _make_arc("A", "B", Decimal("100"))
        arc2 = _make_arc("A", "B", Decimal("50"))
        network = NetworkState(
            period=_PERIOD,
            arcs=[arc1, arc2],
            node_balances={
                "A": _balance("A", Decimal("150")),  # correct for 150 total
                "B": _balance("B", Decimal("-150")),
            },
        )
        result = check_kcl(network)
        assert result.satisfied

    def test_check_kcl_node_count_and_checked_count(self) -> None:
        """node_count equals the number of distinct nodes in the network."""
        arcs = [
            _make_arc("X", "Y", Decimal("10")),
            _make_arc("Y", "Z", Decimal("10")),
        ]
        network = NetworkState(
            period=_PERIOD,
            arcs=arcs,
            node_balances={
                "X": _balance("X", Decimal("10")),
                "Y": _balance("Y", Decimal("0")),
                "Z": _balance("Z", Decimal("-10")),
            },
        )
        result = check_kcl(network)
        assert result.node_count == 3
        assert result.checked_count == 3


# ---------------------------------------------------------------------------
# Unit tests — _provenance_node helper
# ---------------------------------------------------------------------------


class TestProvenanceNode:
    def test_standard_format(self) -> None:
        s = "Law 1 (KCL) for node 'my_node', period 2024-Q4"
        assert _provenance_node(s) == "my_node"

    def test_node_with_special_chars(self) -> None:
        s = "Law 1 (KCL) for node 'fhlb:district-8', period 2020-Q1"
        assert _provenance_node(s) == "fhlb:district-8"

    def test_unrecognised_format_returns_none(self) -> None:
        assert _provenance_node("something random") is None


# ---------------------------------------------------------------------------
# Integration smoke test: round-trip build → check
# ---------------------------------------------------------------------------


class TestBuildCheckRoundTrip:
    def test_satisfied_network_round_trip(self) -> None:
        """build_kcl_rows constraints are all satisfied when evaluated on the network."""
        arcs = [
            _make_arc("MetLife", "FHLB", Decimal("5000")),
            _make_arc("Prudential", "FHLB", Decimal("3000")),
            _make_arc("FHLB", "MetLife", Decimal("200")),  # small reverse flow
        ]
        node_balances = {
            # MetLife: outgoing=5000, incoming=200 → E = 5000 - 200 = 4800
            "MetLife": _balance("MetLife", Decimal("4800")),
            # Prudential: outgoing=3000, incoming=0 → E = 3000
            "Prudential": _balance("Prudential", Decimal("3000")),
            # FHLB: outgoing=200, incoming=8000 → E = 200 - 8000 = -7800
            "FHLB": _balance("FHLB", Decimal("-7800")),
        }
        network = NetworkState(period=_PERIOD, arcs=arcs, node_balances=node_balances)

        cs = build_kcl_rows(network)
        result = check_kcl(network)

        # All constraints should be satisfied.
        assert result.satisfied
        assert len(cs.constraints) == 3

        for c in cs.constraints:
            lhs = sum(
                (coeff * network.arc_value(ak) for ak, coeff in c.matrix_row.items()),
                start=Decimal("0"),
            )
            assert abs(lhs - c.rhs) <= Decimal("0.01"), c.provenance

    def test_direct_measured_arcs_in_round_trip(self) -> None:
        """Direct-measured arcs fold into RHS; the remaining system is consistent."""
        direct = _make_arc(
            "Insurer", "FHLB", Decimal("1000"), flag=DataQualityFlag.DIRECT_MEASURED
        )
        unknown = _make_arc("Insurer", "MMF", Decimal("500"))
        node_balances = {
            # Insurer: outgoing = 1000 + 500 = 1500 → E = 1500
            "Insurer": _balance("Insurer", Decimal("1500")),
            "FHLB": _balance("FHLB", Decimal("-1000")),
            "MMF": _balance("MMF", Decimal("-500")),
        }
        network = NetworkState(
            period=_PERIOD, arcs=[direct, unknown], node_balances=node_balances
        )

        cs = build_kcl_rows(network)
        result = check_kcl(network)

        assert result.satisfied

        c_ins = next(
            c for c in cs.constraints if _provenance_node(c.provenance) == "Insurer"
        )
        # The direct arc must not appear as a variable.
        direct_key: ArcKey = ("Insurer", "FHLB", ArcClass.A3.value, str(_PERIOD))
        assert direct_key not in c_ins.matrix_row
        # The unknown arc must appear as a variable.
        unknown_key: ArcKey = ("Insurer", "MMF", ArcClass.A3.value, str(_PERIOD))
        assert unknown_key in c_ins.matrix_row
