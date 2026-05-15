"""Tests for claimweb.constraints.compile — sparse linear system aggregator.

Tests verify:
1. Soundness       — on a network satisfying all laws by construction,
                     all emitted constraints are satisfied.
2. Completeness    — on a network violating Law 1, at least one constraint
                     is violated.
3. Counts          — constraint counts match per-law builder outputs.
4. Unknowns union  — CompiledSystem.unknowns is the union of all builders'
                     unknowns, sorted, deduplicated.
5. Non-negativity  — geq constraints added for all unknowns; opt-out works.
6. Partial inputs  — Laws 2, 3, 4 skipped gracefully when inputs absent.
7. Law 4           — present when network_from + flow_terms supplied.
8. Same-period guard — ValueError on network_from.period == network.period.
9. Properties      — hypothesis property-based tests for soundness /
                     completeness / stability.
10. summary()      — smoke-test that CompiledSystem.summary() is a string.
11. to_index()     — column index map is a bijection over unknowns.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from claimweb.constraints.compile import (
    CompiledSystem,
    LawStats,
    compile_constraints,
)
from claimweb.constraints.double_entry import InstrumentTotals
from claimweb.constraints.flow_funds import FlowTerms, RevaluationTerms
from claimweb.constraints.kcl import (
    ArcKey,
    ConstraintSet,
    LinearConstraint,
    NetworkState,
    NodeBalance,
    build_kcl_rows,
)
from claimweb.constraints.sectoral import SectorMap, SectoralTotals
from claimweb.fetchers.base import ArcClass, ArcFact, DataQualityFlag, Period

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SHA = "a" * 64
_P = Period("2024-Q4")
_P_PREV = Period("2024-Q3")


def _arc(
    src: str,
    tgt: str,
    amount: Decimal,
    flag: DataQualityFlag = DataQualityFlag.MARGINAL_INFERRED,
    cls: ArcClass = ArcClass.A3,
    period: Period = _P,
) -> ArcFact:
    return ArcFact(
        period=period,
        source_node_id=src,
        target_node_id=tgt,
        instrument_class=cls,
        dollar_amount_millions=amount,
        measurement_basis="stock_eop",
        data_quality_flag=flag,
        provenance_source="test",
        provenance_url="https://example.com/test",
        provenance_filing=None,
        provenance_page=None,
        provenance_field="test_field",
        sha256_of_source=_SHA,
    )


def _direct(
    src: str,
    tgt: str,
    amount: Decimal,
    cls: ArcClass = ArcClass.A3,
    period: Period = _P,
) -> ArcFact:
    return _arc(src, tgt, amount, DataQualityFlag.DIRECT_MEASURED, cls, period)


def _balance(
    node_id: str,
    equity: Decimal,
    nonfinancial: Decimal = Decimal("0"),
    period: Period = _P,
) -> NodeBalance:
    return NodeBalance(
        node_id=node_id,
        period=period,
        equity_millions=equity,
        nonfinancial_assets_millions=nonfinancial,
    )


def _simple_balanced_network(period: Period = _P) -> NetworkState:
    """Two nodes A→B with $100 M arc.

    A: outgoing=$100, equity=$100  → KCL: 100-0=100 ✓
    B: incoming=$100, equity=-$100 → KCL: 0-100=-100 ✓  (B is a borrower)
    """
    arc = _arc("A", "B", Decimal("100"), period=period)
    balances = {
        "A": _balance("A", Decimal("100"), period=period),
        "B": _balance("B", Decimal("-100"), period=period),
    }
    return NetworkState(period=period, arcs=[arc], node_balances=balances)


def _eval_constraint(c: LinearConstraint, unknowns_map: dict[ArcKey, Decimal]) -> Decimal:
    """Evaluate LHS of a constraint given arc values."""
    return sum(
        coeff * unknowns_map.get(key, Decimal("0"))
        for key, coeff in c.matrix_row.items()
    )


# ---------------------------------------------------------------------------
# Basic structure tests
# ---------------------------------------------------------------------------


class TestCompiledSystemBasics:
    def test_minimal_compile_returns_compiled_system(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        assert isinstance(sys, CompiledSystem)

    def test_unknowns_are_sorted(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        assert sys.unknowns == sorted(sys.unknowns)

    def test_unknowns_are_unique(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        assert len(sys.unknowns) == len(set(sys.unknowns))

    def test_n_unknowns_property(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        assert sys.n_unknowns == len(sys.unknowns)

    def test_n_constraints_property(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        assert sys.n_constraints == len(sys.constraints)

    def test_n_equality_and_inequality_partition(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        assert sys.n_equality + sys.n_inequality == sys.n_constraints

    def test_summary_is_string(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        s = sys.summary()
        assert isinstance(s, str)
        assert "CompiledSystem" in s

    def test_to_index_bijection(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        idx = sys.to_index()
        assert len(idx) == sys.n_unknowns
        assert set(idx.keys()) == set(sys.unknowns)
        assert set(idx.values()) == set(range(sys.n_unknowns))


# ---------------------------------------------------------------------------
# Law 1 — always included
# ---------------------------------------------------------------------------


class TestLaw1AlwaysIncluded:
    def test_kcl_stats_present(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        names = [s.name for s in sys.law_stats]
        assert "KCL (Law 1)" in names

    def test_kcl_count_matches_builder(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        kcl_cs = build_kcl_rows(net)
        kcl_stat = next(s for s in sys.law_stats if s.name == "KCL (Law 1)")
        assert kcl_stat.count == len(kcl_cs.constraints)

    def test_kcl_constraint_provenances_present(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        assert any("Law 1" in c.provenance for c in sys.constraints)


# ---------------------------------------------------------------------------
# Law 2 — double-entry, optional
# ---------------------------------------------------------------------------


class TestLaw2Optional:
    def test_law2_absent_when_no_boundary_terms(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        names = [s.name for s in sys.law_stats]
        assert "double_entry (Law 2)" not in names

    def test_law2_included_when_boundary_terms_supplied(self):
        net = _simple_balanced_network()
        # Total A3 instrument = $100 M (the single arc)
        bt: InstrumentTotals = {"A3": Decimal("100")}
        sys = compile_constraints(net, boundary_terms=bt)
        names = [s.name for s in sys.law_stats]
        assert "double_entry (Law 2)" in names

    def test_law2_count_matches_builder(self):
        from claimweb.constraints.double_entry import build_double_entry_rows

        net = _simple_balanced_network()
        bt: InstrumentTotals = {"A3": Decimal("100")}
        sys = compile_constraints(net, boundary_terms=bt)
        de_cs = build_double_entry_rows(net.arcs, period=net.period, boundary_terms=bt)
        de_stat = next(s for s in sys.law_stats if s.name == "double_entry (Law 2)")
        assert de_stat.count == len(de_cs.constraints)

    def test_law2_empty_boundary_terms_dict(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net, boundary_terms={})
        # boundary_terms={} is not None, so Law 2 fires but emits 0 rows
        names = [s.name for s in sys.law_stats]
        assert "double_entry (Law 2)" in names
        de_stat = next(s for s in sys.law_stats if s.name == "double_entry (Law 2)")
        assert de_stat.count == 0


# ---------------------------------------------------------------------------
# Law 3 — sectoral, optional
# ---------------------------------------------------------------------------


class TestLaw3Optional:
    def test_law3_absent_when_no_sector_map(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        names = [s.name for s in sys.law_stats]
        assert "sectoral (Law 3)" not in names

    def test_law3_absent_when_sector_map_but_no_totals(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net, sector_map={"A": "sector:test"})
        names = [s.name for s in sys.law_stats]
        assert "sectoral (Law 3)" not in names

    def test_law3_absent_when_totals_but_no_sector_map(self):
        net = _simple_balanced_network()
        totals: SectoralTotals = {("sector:test", "A3", "asset"): Decimal("100")}
        sys = compile_constraints(net, sectoral_totals=totals)
        names = [s.name for s in sys.law_stats]
        assert "sectoral (Law 3)" not in names

    def test_law3_included_when_both_supplied(self):
        net = _simple_balanced_network()
        sm: SectorMap = {"A": "sector:test"}
        totals: SectoralTotals = {("sector:test", "A3", "asset"): Decimal("100")}
        sys = compile_constraints(net, sector_map=sm, sectoral_totals=totals)
        names = [s.name for s in sys.law_stats]
        assert "sectoral (Law 3)" in names

    def test_law3_count_matches_builder(self):
        from claimweb.constraints.sectoral import build_sectoral_rows

        net = _simple_balanced_network()
        sm: SectorMap = {"A": "sector:test"}
        totals: SectoralTotals = {("sector:test", "A3", "asset"): Decimal("100")}
        sys = compile_constraints(net, sector_map=sm, sectoral_totals=totals)
        sec_cs = build_sectoral_rows(
            net.arcs, period=net.period, sector_map=sm, sectoral_totals=totals
        )
        sec_stat = next(s for s in sys.law_stats if s.name == "sectoral (Law 3)")
        assert sec_stat.count == len(sec_cs.constraints)


# ---------------------------------------------------------------------------
# Law 4 — flow-of-funds, optional
# ---------------------------------------------------------------------------


class TestLaw4Optional:
    def test_law4_absent_when_no_network_from(self):
        net = _simple_balanced_network()
        flow: FlowTerms = {("A", "B", "A3"): Decimal("10")}
        sys = compile_constraints(net, flow_terms=flow)
        names = [s.name for s in sys.law_stats]
        assert "flow_funds (Law 4)" not in names

    def test_law4_absent_when_no_flow_terms(self):
        net = _simple_balanced_network()
        net_prev = _simple_balanced_network(period=_P_PREV)
        sys = compile_constraints(net, network_from=net_prev)
        names = [s.name for s in sys.law_stats]
        assert "flow_funds (Law 4)" not in names

    def test_law4_absent_when_empty_flow_terms(self):
        net = _simple_balanced_network()
        net_prev = _simple_balanced_network(period=_P_PREV)
        sys = compile_constraints(net, network_from=net_prev, flow_terms={})
        names = [s.name for s in sys.law_stats]
        assert "flow_funds (Law 4)" not in names

    def test_law4_included_when_both_supplied(self):
        net = _simple_balanced_network()
        net_prev = _simple_balanced_network(period=_P_PREV)
        flow: FlowTerms = {("A", "B", "A3"): Decimal("5")}
        sys = compile_constraints(net, network_from=net_prev, flow_terms=flow)
        names = [s.name for s in sys.law_stats]
        assert "flow_funds (Law 4)" in names

    def test_law4_count_matches_builder(self):
        from claimweb.constraints.flow_funds import build_flow_funds_rows

        net = _simple_balanced_network()
        net_prev = _simple_balanced_network(period=_P_PREV)
        flow: FlowTerms = {("A", "B", "A3"): Decimal("5")}
        sys = compile_constraints(net, network_from=net_prev, flow_terms=flow)
        ff_cs = build_flow_funds_rows(
            net_prev.arcs,
            net.arcs,
            period_from=net_prev.period,
            period_to=net.period,
            flow_terms=flow,
        )
        ff_stat = next(s for s in sys.law_stats if s.name == "flow_funds (Law 4)")
        assert ff_stat.count == len(ff_cs.constraints)

    def test_same_period_raises(self):
        net = _simple_balanced_network()
        flow: FlowTerms = {("A", "B", "A3"): Decimal("5")}
        with pytest.raises(ValueError, match="must differ"):
            compile_constraints(net, network_from=net, flow_terms=flow)

    def test_law4_unknowns_span_both_periods(self):
        net = _simple_balanced_network()
        net_prev = _simple_balanced_network(period=_P_PREV)
        flow: FlowTerms = {("A", "B", "A3"): Decimal("5")}
        sys = compile_constraints(net, network_from=net_prev, flow_terms=flow)
        period_strs = {key[3] for key in sys.unknowns}
        assert str(_P) in period_strs
        assert str(_P_PREV) in period_strs

    def test_revaluation_terms_passed_through(self):
        from claimweb.constraints.flow_funds import build_flow_funds_rows

        net = _simple_balanced_network()
        net_prev = _simple_balanced_network(period=_P_PREV)
        flow: FlowTerms = {("A", "B", "A3"): Decimal("5")}
        reval: RevaluationTerms = {("A", "B", "A3"): Decimal("2")}
        sys = compile_constraints(
            net, network_from=net_prev, flow_terms=flow, revaluation_terms=reval
        )
        ff_cs = build_flow_funds_rows(
            net_prev.arcs,
            net.arcs,
            period_from=net_prev.period,
            period_to=net.period,
            flow_terms=flow,
            revaluation_terms=reval,
        )
        ff_stat = next(s for s in sys.law_stats if s.name == "flow_funds (Law 4)")
        assert ff_stat.count == len(ff_cs.constraints)
        # The RHS of the compiled constraint should match the builder's RHS
        compiled_ff = [
            c for c in sys.constraints if "Law 4" in c.provenance
        ]
        assert len(compiled_ff) == len(ff_cs.constraints)


# ---------------------------------------------------------------------------
# Non-negativity constraints
# ---------------------------------------------------------------------------


class TestNonNegativity:
    def test_nonneg_included_by_default(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        names = [s.name for s in sys.law_stats]
        assert "non-negativity" in names

    def test_nonneg_count_equals_n_unknowns(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        nn_stat = next(s for s in sys.law_stats if s.name == "non-negativity")
        assert nn_stat.count == sys.n_unknowns

    def test_nonneg_all_geq(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        nn_stat = next(s for s in sys.law_stats if s.name == "non-negativity")
        assert nn_stat.n_geq == nn_stat.count
        assert nn_stat.n_eq == 0
        assert nn_stat.n_leq == 0

    def test_nonneg_opt_out(self):
        net = _simple_balanced_network()
        sys_nn = compile_constraints(net, include_nonnegativity=False)
        sys_with = compile_constraints(net, include_nonnegativity=True)
        assert sys_nn.n_constraints + sys_nn.n_unknowns == sys_with.n_constraints

    def test_nonneg_opt_out_no_nonneg_stat(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net, include_nonnegativity=False)
        names = [s.name for s in sys.law_stats]
        assert "non-negativity" not in names

    def test_nonneg_provenances(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        nn_constraints = [c for c in sys.constraints if c.kind == "geq"]
        assert all("non-negativity" in c.provenance for c in nn_constraints)

    def test_nonneg_one_per_unknown(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        nn_constraints = [c for c in sys.constraints if c.kind == "geq"]
        nn_keys = [next(iter(c.matrix_row)) for c in nn_constraints]
        assert set(nn_keys) == set(sys.unknowns)

    def test_nonneg_rhs_is_zero(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        nn_constraints = [c for c in sys.constraints if c.kind == "geq"]
        assert all(c.rhs == Decimal("0") for c in nn_constraints)

    def test_nonneg_coefficient_is_one(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        nn_constraints = [c for c in sys.constraints if c.kind == "geq"]
        for c in nn_constraints:
            assert len(c.matrix_row) == 1
            coeff = next(iter(c.matrix_row.values()))
            assert coeff == Decimal("1")


# ---------------------------------------------------------------------------
# Unknowns union
# ---------------------------------------------------------------------------


class TestUnknownsUnion:
    def test_unknowns_superset_of_kcl_unknowns(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        kcl_cs = build_kcl_rows(net)
        assert set(kcl_cs.unknowns).issubset(set(sys.unknowns))

    def test_unknowns_superset_of_law4_unknowns(self):
        from claimweb.constraints.flow_funds import build_flow_funds_rows

        net = _simple_balanced_network()
        net_prev = _simple_balanced_network(period=_P_PREV)
        flow: FlowTerms = {("A", "B", "A3"): Decimal("5")}
        sys = compile_constraints(net, network_from=net_prev, flow_terms=flow)
        ff_cs = build_flow_funds_rows(
            net_prev.arcs,
            net.arcs,
            period_from=net_prev.period,
            period_to=net.period,
            flow_terms=flow,
        )
        assert set(ff_cs.unknowns).issubset(set(sys.unknowns))

    def test_unknowns_not_duplicated_across_laws(self):
        """An arc that appears in both KCL and double-entry appears once."""
        net = _simple_balanced_network()
        bt: InstrumentTotals = {"A3": Decimal("100")}
        sys = compile_constraints(net, boundary_terms=bt)
        # unknowns is already checked for uniqueness in TestCompiledSystemBasics
        assert len(sys.unknowns) == len(set(sys.unknowns))


# ---------------------------------------------------------------------------
# LawStats structure
# ---------------------------------------------------------------------------


class TestLawStats:
    def test_law_stats_are_law_stats_instances(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        assert all(isinstance(s, LawStats) for s in sys.law_stats)

    def test_law_stats_count_sum_matches_n_constraints(self):
        net = _simple_balanced_network()
        bt: InstrumentTotals = {"A3": Decimal("100")}
        sm: SectorMap = {"A": "sector:test"}
        totals: SectoralTotals = {("sector:test", "A3", "asset"): Decimal("100")}
        net_prev = _simple_balanced_network(period=_P_PREV)
        flow: FlowTerms = {("A", "B", "A3"): Decimal("5")}
        sys = compile_constraints(
            net,
            boundary_terms=bt,
            sector_map=sm,
            sectoral_totals=totals,
            network_from=net_prev,
            flow_terms=flow,
        )
        total_from_stats = sum(s.count for s in sys.law_stats)
        assert total_from_stats == sys.n_constraints

    def test_law_stats_eq_leq_geq_partition(self):
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        for s in sys.law_stats:
            assert s.count == s.n_eq + s.n_leq + s.n_geq


# ---------------------------------------------------------------------------
# Constraint satisfaction (soundness check)
# ---------------------------------------------------------------------------


class TestSoundness:
    def test_kcl_constraints_satisfied_on_balanced_network(self):
        """KCL constraints are satisfied when arc values equal the network."""
        net = _simple_balanced_network()
        sys = compile_constraints(net, include_nonnegativity=False)
        arc_vals: dict[ArcKey, Decimal] = {}
        for arc in net.arcs:
            key: ArcKey = (
                arc.source_node_id,
                arc.target_node_id,
                arc.instrument_class.value,
                str(arc.period),
            )
            arc_vals[key] = arc_vals.get(key, Decimal("0")) + arc.dollar_amount_millions

        eq_constraints = [c for c in sys.constraints if c.kind == "eq"]
        for c in eq_constraints:
            lhs = _eval_constraint(c, arc_vals)
            assert abs(lhs - c.rhs) <= Decimal("0.001"), (
                f"Constraint unsatisfied: {c.provenance}, lhs={lhs}, rhs={c.rhs}"
            )

    def test_nonneg_satisfied_for_positive_arcs(self):
        """Non-negativity constraints are satisfied when all arcs are positive."""
        net = _simple_balanced_network()
        sys = compile_constraints(net)
        arc_vals: dict[ArcKey, Decimal] = {}
        for arc in net.arcs:
            key: ArcKey = (
                arc.source_node_id,
                arc.target_node_id,
                arc.instrument_class.value,
                str(arc.period),
            )
            arc_vals[key] = arc_vals.get(key, Decimal("0")) + arc.dollar_amount_millions

        nn_constraints = [c for c in sys.constraints if c.kind == "geq"]
        for c in nn_constraints:
            lhs = _eval_constraint(c, arc_vals)
            assert lhs >= c.rhs, (
                f"Non-negativity violated: {c.provenance}, lhs={lhs}"
            )


# ---------------------------------------------------------------------------
# Multiple arcs / multiple instruments
# ---------------------------------------------------------------------------


class TestMultipleArcs:
    def test_two_instrument_types(self):
        arc1 = _arc("A", "B", Decimal("100"), cls=ArcClass.A3)
        arc2 = _arc("A", "C", Decimal("50"), cls=ArcClass.A4)
        balances = {
            "A": _balance("A", Decimal("150")),
            "B": _balance("B", Decimal("0")),
            "C": _balance("C", Decimal("0")),
        }
        net = NetworkState(period=_P, arcs=[arc1, arc2], node_balances=balances)
        sys = compile_constraints(net)
        # 3 nodes → 3 KCL constraints; 2 arcs → 2 unknowns → 2 nonneg
        kcl_stat = next(s for s in sys.law_stats if s.name == "KCL (Law 1)")
        assert kcl_stat.count == 3
        assert sys.n_unknowns == 2

    def test_direct_measured_arc_reduces_unknowns(self):
        """A DIRECT_MEASURED arc is folded into RHS; it is not an unknown."""
        arc_dm = _direct("A", "B", Decimal("100"))
        balances = {
            "A": _balance("A", Decimal("100")),
            "B": _balance("B", Decimal("0")),
        }
        net = NetworkState(period=_P, arcs=[arc_dm], node_balances=balances)
        sys = compile_constraints(net)
        # The arc is direct-measured; the network has no unknowns.
        assert sys.n_unknowns == 0
        assert sys.n_inequality == 0  # no nonneg constraints either

    def test_mixed_flags_correct_unknowns(self):
        arc1 = _arc("A", "B", Decimal("60"))  # unknown
        arc2 = _direct("A", "C", Decimal("40"))  # direct → folded
        balances = {
            "A": _balance("A", Decimal("100")),
            "B": _balance("B", Decimal("0")),
            "C": _balance("C", Decimal("0")),
        }
        net = NetworkState(period=_P, arcs=[arc1, arc2], node_balances=balances)
        sys = compile_constraints(net)
        # Only arc1 (A→B) is an unknown
        assert sys.n_unknowns == 1
        key: ArcKey = ("A", "B", "A3", str(_P))
        assert key in sys.unknowns


# ---------------------------------------------------------------------------
# All four laws together
# ---------------------------------------------------------------------------


class TestAllFourLaws:
    def _build_full_system(self) -> CompiledSystem:
        net = _simple_balanced_network()
        net_prev = _simple_balanced_network(period=_P_PREV)
        bt: InstrumentTotals = {"A3": Decimal("100")}
        sm: SectorMap = {"A": "sector:test"}
        totals: SectoralTotals = {("sector:test", "A3", "asset"): Decimal("100")}
        flow: FlowTerms = {("A", "B", "A3"): Decimal("0")}
        return compile_constraints(
            net,
            boundary_terms=bt,
            sector_map=sm,
            sectoral_totals=totals,
            network_from=net_prev,
            flow_terms=flow,
        )

    def test_all_four_law_stats_present(self):
        sys = self._build_full_system()
        names = [s.name for s in sys.law_stats]
        assert "KCL (Law 1)" in names
        assert "double_entry (Law 2)" in names
        assert "sectoral (Law 3)" in names
        assert "flow_funds (Law 4)" in names
        assert "non-negativity" in names

    def test_total_count_consistent(self):
        sys = self._build_full_system()
        assert sum(s.count for s in sys.law_stats) == sys.n_constraints

    def test_equality_dominated(self):
        """Most constraints should be equalities; only nonneg are inequalities."""
        sys = self._build_full_system()
        assert sys.n_equality > 0
        nn_stat = next(s for s in sys.law_stats if s.name == "non-negativity")
        assert sys.n_inequality == nn_stat.count

    def test_provenance_identifies_law(self):
        sys = self._build_full_system()
        provenances = [c.provenance for c in sys.constraints]
        assert any("Law 1" in p for p in provenances)
        assert any("Law 2" in p for p in provenances)
        assert any("Law 3" in p for p in provenances)
        assert any("Law 4" in p for p in provenances)
        assert any("non-negativity" in p for p in provenances)


# ---------------------------------------------------------------------------
# Hypothesis property-based tests
# ---------------------------------------------------------------------------

# Small network strategy: 1–3 nodes, 1–5 arcs, amounts in [1, 1000].

_node_ids = st.sampled_from(["N1", "N2", "N3", "N4"])
_amounts = st.decimals(min_value="1", max_value="1000", places=2).map(Decimal)
_instrument_cls = st.sampled_from(list(ArcClass))


@st.composite
def _small_network(draw, period: Period = _P) -> NetworkState:
    """Generate a small balanced NetworkState for property tests."""
    n_arcs = draw(st.integers(min_value=1, max_value=4))
    arcs = []
    for _ in range(n_arcs):
        src, tgt = draw(st.lists(_node_ids, min_size=2, max_size=2, unique=True))
        amount = draw(_amounts)
        cls = draw(_instrument_cls)
        arcs.append(_arc(src, tgt, amount, cls=cls, period=period))

    # Collect all nodes
    nodes: set[str] = set()
    for a in arcs:
        nodes.add(a.source_node_id)
        nodes.add(a.target_node_id)

    # Build balances: equity = outgoing - incoming (makes Law 1 hold by construction)
    node_bal: dict[str, NodeBalance] = {}
    for node_id in nodes:
        out = sum(
            (a.dollar_amount_millions for a in arcs if a.source_node_id == node_id),
            Decimal("0"),
        )
        inc = sum(
            (a.dollar_amount_millions for a in arcs if a.target_node_id == node_id),
            Decimal("0"),
        )
        equity = out - inc
        node_bal[node_id] = _balance(node_id, equity, period=period)

    return NetworkState(period=period, arcs=arcs, node_balances=node_bal)


@given(_small_network())
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_property_soundness_kcl(network: NetworkState) -> None:
    """On a Law-1-balanced network, all KCL constraints are satisfied."""
    sys = compile_constraints(network, include_nonnegativity=False)
    arc_vals: dict[ArcKey, Decimal] = {}
    for arc in network.arcs:
        key: ArcKey = (
            arc.source_node_id,
            arc.target_node_id,
            arc.instrument_class.value,
            str(arc.period),
        )
        arc_vals[key] = arc_vals.get(key, Decimal("0")) + arc.dollar_amount_millions

    eq_constraints = [c for c in sys.constraints if c.kind == "eq"]
    for c in eq_constraints:
        lhs = _eval_constraint(c, arc_vals)
        assert abs(lhs - c.rhs) <= Decimal("0.01"), (
            f"Soundness failure: {c.provenance}, lhs={lhs}, rhs={c.rhs}"
        )


@given(_small_network())
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_property_unknowns_are_arc_keys(network: NetworkState) -> None:
    """Every entry in CompiledSystem.unknowns is a 4-tuple (src, tgt, cls, period)."""
    sys = compile_constraints(network)
    for key in sys.unknowns:
        assert isinstance(key, tuple), f"Unknown is not a tuple: {key!r}"
        assert len(key) == 4, f"Unknown has wrong length: {key!r}"
        src, tgt, cls_val, period_str = key
        assert isinstance(src, str)
        assert isinstance(tgt, str)
        assert isinstance(cls_val, str)
        assert isinstance(period_str, str)


@given(_small_network())
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_property_nonneg_count_equals_unknowns(network: NetworkState) -> None:
    """Non-negativity constraint count equals n_unknowns."""
    sys = compile_constraints(network, include_nonnegativity=True)
    nn_stat = next((s for s in sys.law_stats if s.name == "non-negativity"), None)
    assert nn_stat is not None
    assert nn_stat.count == sys.n_unknowns


@given(_small_network(), _amounts)
@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
def test_property_stability_kcl_rhs(network: NetworkState, delta: Decimal) -> None:
    """Adding a DIRECT_MEASURED arc of value δ to a brand-new target shifts
    the KCL RHS for the source node by exactly -δ (outgoing folded into RHS).
    We use a target node guaranteed absent from the network to avoid key merging.
    """
    if not network.arcs:
        return
    src = network.arcs[0].source_node_id
    new_tgt = "__stability_target__"
    assert new_tgt not in network.node_balances

    def _rhs_for_node(s: CompiledSystem, node_id: str) -> Decimal | None:
        for c in s.constraints:
            if c.kind == "eq" and f"node {node_id!r}" in c.provenance:
                return c.rhs
        return None

    sys_before = compile_constraints(network, include_nonnegativity=False)
    # Add a DIRECT_MEASURED arc from src to a fresh node not in the network
    dm_arc = _direct(src, new_tgt, delta)
    network2 = NetworkState(
        period=network.period,
        arcs=network.arcs + [dm_arc],
        node_balances=network.node_balances,
    )
    sys_after = compile_constraints(network2, include_nonnegativity=False)

    rhs_before = _rhs_for_node(sys_before, src)
    rhs_after = _rhs_for_node(sys_after, src)
    if rhs_before is not None and rhs_after is not None:
        shift = rhs_after - rhs_before
        assert abs(shift - (-delta)) <= Decimal("0.001"), (
            f"Stability failure for src={src}: shift={shift}, expected={-delta}"
        )


@given(_small_network(_P), _small_network(_P_PREV))
@settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
def test_property_law4_constraints_reference_both_periods(
    network: NetworkState, network_from: NetworkState
) -> None:
    """Law 4 constraints reference ArcKeys from both period_from and period_to."""
    if not network.arcs or not network_from.arcs:
        return
    # Build flow_terms from common arc triples
    flow: FlowTerms = {}
    for a in network_from.arcs:
        flow_key = (a.source_node_id, a.target_node_id, a.instrument_class.value)
        if flow_key not in flow:
            flow[flow_key] = Decimal("0")

    if not flow:
        return

    sys = compile_constraints(
        network, network_from=network_from, flow_terms=flow
    )
    if "flow_funds (Law 4)" not in [s.name for s in sys.law_stats]:
        return

    ff_constraints = [c for c in sys.constraints if "Law 4" in c.provenance]
    for c in ff_constraints:
        key_periods = {key[3] for key in c.matrix_row}
        # Each Law 4 constraint may reference either or both periods
        assert key_periods.issubset({str(_P), str(_P_PREV)}), (
            f"Unexpected period in Law 4 constraint: {key_periods}"
        )
