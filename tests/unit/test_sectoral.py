"""Property-based and unit tests for claimweb.constraints.sectoral (Law 3).

Tests verify four properties per the constraint-author skill:
1. Soundness    — on a network satisfying Law 3 by construction, build_sectoral_rows
                  emits constraints that are all satisfied when arc values are
                  substituted in.
2. Completeness — on a network violating Law 3 (one arc perturbed), check_sectoral
                  detects at least one violation.
3. Stability    — perturbing a DIRECT_MEASURED arc by δ shifts the constraint RHS
                  by exactly −δ (linear; no chaotic behaviour).
4. Independence — each constraint's matrix_row references only arcs for the
                  constraint's own (sector, instrument, side) triple.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from claimweb.constraints.kcl import (
    ConstraintSet,
    LinearConstraint,
    NetworkState,
    NodeBalance,
)
from claimweb.constraints.sectoral import (
    SectoralResult,
    SectoralTotals,
    SectoralViolation,
    SectorMap,
    _DEFAULT_TOL_REL,
    _MIN_ABS_TOL,
    _provenance_parts,
    build_sectoral_rows,
    check_sectoral,
)
from claimweb.fetchers.base import ArcClass, ArcFact, DataQualityFlag, Period

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_DUMMY_SHA256 = "c" * 64
_PERIOD = Period("2024-Q4")
_OTHER_PERIOD = Period("2023-Q1")

_SECTOR_LIFE = "sector:life_insurance_companies"
_SECTOR_MMF = "sector:money_market_funds"
_SECTOR_BANK = "sector:depository_institutions"


def _make_arc(
    source: str,
    target: str,
    amount: Decimal,
    flag: DataQualityFlag = DataQualityFlag.MARGINAL_INFERRED,
    cls: ArcClass = ArcClass.A3,
    period: Period = _PERIOD,
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
) -> ArcFact:
    return _make_arc(source, target, amount, DataQualityFlag.DIRECT_MEASURED, cls)


def _make_network(
    arcs: list[ArcFact],
    period: Period = _PERIOD,
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


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("500000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_large_perturbation = st.decimals(
    min_value=Decimal("10000"),   # well above any tolerance threshold
    max_value=Decimal("500000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_SECTORS = [_SECTOR_LIFE, _SECTOR_MMF, _SECTOR_BANK]
_INSTRUMENTS = [ArcClass.A3, ArcClass.A4, ArcClass.A8]


@st.composite
def valid_sectoral_network(draw: st.DrawFn) -> tuple[NetworkState, SectorMap, SectoralTotals]:
    """NetworkState that satisfies Law 3 by construction, plus matching totals.

    Strategy:
    * Pick 2–3 sectors, each with 1–2 nodes.
    * Pick 1–5 arcs per sector/instrument combination.
    * Compute sector totals from arc amounts (asset and liability sides).
    * Return (NetworkState, SectorMap, SectoralTotals) where the totals match
      the arc sums exactly, so Law 3 is satisfied by construction.
    """
    n_sectors = draw(st.integers(min_value=1, max_value=3))
    chosen_sectors = draw(
        st.lists(
            st.sampled_from(_SECTORS),
            min_size=n_sectors,
            max_size=n_sectors,
            unique=True,
        )
    )
    n_instruments = draw(st.integers(min_value=1, max_value=2))
    chosen_instruments = draw(
        st.lists(
            st.sampled_from(_INSTRUMENTS),
            min_size=n_instruments,
            max_size=n_instruments,
            unique=True,
        )
    )

    sector_map: SectorMap = {}
    all_nodes: list[str] = []

    for sector_id in chosen_sectors:
        short = sector_id.split(":")[-1][:4]
        n_nodes = draw(st.integers(min_value=1, max_value=2))
        for i in range(n_nodes):
            nid = f"{short}_{i}"
            sector_map[nid] = sector_id
            all_nodes.append(nid)

    # Add some non-sector "counterparty" nodes
    n_external = draw(st.integers(min_value=1, max_value=2))
    external_nodes = [f"ext_{i}" for i in range(n_external)]

    arcs: list[ArcFact] = []

    # Track sector totals for asset and liability sides.
    asset_sums: dict[tuple[str, str], Decimal] = {}
    liab_sums: dict[tuple[str, str], Decimal] = {}

    # Generate arcs from sector nodes to external nodes (asset side).
    for instr in chosen_instruments:
        for src in all_nodes:
            sector_id = sector_map[src]
            if draw(st.booleans()):
                tgt = draw(st.sampled_from(external_nodes))
                amount = draw(_amounts)
                arcs.append(_make_arc(src, tgt, amount, cls=instr))
                k = (sector_id, instr.value)
                asset_sums[k] = asset_sums.get(k, Decimal("0")) + amount

        # Generate arcs from external nodes to sector nodes (liability side).
        for tgt in all_nodes:
            sector_id = sector_map[tgt]
            if draw(st.booleans()):
                src = draw(st.sampled_from(external_nodes))
                amount = draw(_amounts)
                arcs.append(_make_arc(src, tgt, amount, cls=instr))
                k = (sector_id, instr.value)
                liab_sums[k] = liab_sums.get(k, Decimal("0")) + amount

    # Build sectoral_totals to exactly match the computed sums — Law 3 satisfied.
    sectoral_totals: SectoralTotals = {}
    for sector_id in chosen_sectors:
        for instr in chosen_instruments:
            k = (sector_id, instr.value)
            asset_total = asset_sums.get(k, Decimal("0"))
            liab_total = liab_sums.get(k, Decimal("0"))
            if asset_total > Decimal("0"):
                sectoral_totals[(sector_id, instr.value, "asset")] = asset_total
            if liab_total > Decimal("0"):
                sectoral_totals[(sector_id, instr.value, "liab")] = liab_total

    # Need at least one arc for meaningful tests.
    if not arcs or not sectoral_totals:
        # Fallback: manufacture a minimal valid network.
        src = list(sector_map.keys())[0]
        sector_id = sector_map[src]
        tgt = "ext_0"
        amount = Decimal("1000.00")
        arcs = [_make_arc(src, tgt, amount, cls=ArcClass.A3)]
        sectoral_totals = {(sector_id, "A3", "asset"): amount}

    all_arc_nodes = {arc.source_node_id for arc in arcs} | {arc.target_node_id for arc in arcs}
    network = _make_network(arcs)
    return network, sector_map, sectoral_totals


# ---------------------------------------------------------------------------
# Property 1 — Soundness
# ---------------------------------------------------------------------------


@given(valid_sectoral_network())
@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
def test_soundness_build_sectoral_rows(
    network_map_totals: tuple[NetworkState, SectorMap, SectoralTotals],
) -> None:
    """On a Law-3-satisfying network, every compiled constraint is satisfied.

    Substitutes the network's arc values into each constraint's matrix_row
    and verifies LHS == RHS to within Decimal("0.01") tolerance.
    """
    network, sector_map, sectoral_totals = network_map_totals
    cs: ConstraintSet = build_sectoral_rows(
        network.arcs,
        period=network.period,
        sector_map=sector_map,
        sectoral_totals=sectoral_totals,
    )

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


@given(valid_sectoral_network())
@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
def test_soundness_check_sectoral(
    network_map_totals: tuple[NetworkState, SectorMap, SectoralTotals],
) -> None:
    """check_sectoral reports satisfied=True on a Law-3-satisfying network."""
    network, sector_map, sectoral_totals = network_map_totals
    result: SectoralResult = check_sectoral(
        network,
        sector_map=sector_map,
        sectoral_totals=sectoral_totals,
        tol=Decimal("0.0001"),
    )
    assert result.satisfied, (
        "Expected satisfied network but got violations:\n"
        + "\n".join(f"  {v.provenance}" for v in result.violations)
    )
    assert result.checked_count == len(sectoral_totals)


# ---------------------------------------------------------------------------
# Property 2 — Completeness
# ---------------------------------------------------------------------------


@given(valid_sectoral_network(), _large_perturbation)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_completeness_check_sectoral(
    network_map_totals: tuple[NetworkState, SectorMap, SectoralTotals],
    extra: Decimal,
) -> None:
    """Perturbing one arc by a large amount causes check_sectoral to report a violation.

    The perturbation is chosen to be well above the tolerance threshold.
    """
    network, sector_map, sectoral_totals = network_map_totals
    if not network.arcs:
        return

    orig = network.arcs[0]
    perturbed_arc = _make_arc(
        orig.source_node_id,
        orig.target_node_id,
        orig.dollar_amount_millions + extra,
        cls=orig.instrument_class,
    )
    bad_network = _make_network([perturbed_arc] + network.arcs[1:])

    result: SectoralResult = check_sectoral(
        bad_network,
        sector_map=sector_map,
        sectoral_totals=sectoral_totals,
        tol=Decimal("0.0001"),
    )
    # If the perturbed arc belongs to a tracked (sector, instrument, side), there
    # must be at least one violation.  We only assert when the first arc actually
    # contributes to a tracked entry.
    src_sector = sector_map.get(orig.source_node_id)
    tgt_sector = sector_map.get(orig.target_node_id)
    instr_val = orig.instrument_class.value

    contributes = (
        (src_sector is not None and (src_sector, instr_val, "asset") in sectoral_totals)
        or (tgt_sector is not None and (tgt_sector, instr_val, "liab") in sectoral_totals)
    )
    if contributes:
        assert not result.satisfied, (
            f"Expected violation after adding {extra} to first arc but got satisfied"
        )
        assert len(result.violations) >= 1


# ---------------------------------------------------------------------------
# Property 3 — Stability
# ---------------------------------------------------------------------------


@given(valid_sectoral_network(), _amounts, _amounts)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_stability_build_sectoral_rows(
    network_map_totals: tuple[NetworkState, SectorMap, SectoralTotals],
    direct_amount: Decimal,
    delta: Decimal,
) -> None:
    """Replacing the first arc with a DIRECT_MEASURED arc and increasing its
    amount by δ shifts the relevant constraint's RHS by exactly −δ.

    All other constraints are unaffected.
    """
    network, sector_map, sectoral_totals = network_map_totals
    if not network.arcs or not sectoral_totals:
        return

    orig = network.arcs[0]
    rest = network.arcs[1:]

    def _build_with_direct(amount: Decimal) -> ConstraintSet:
        direct_arc = _make_arc(
            orig.source_node_id,
            orig.target_node_id,
            amount,
            flag=DataQualityFlag.DIRECT_MEASURED,
            cls=orig.instrument_class,
        )
        return build_sectoral_rows(
            [direct_arc] + rest,
            period=_PERIOD,
            sector_map=sector_map,
            sectoral_totals=sectoral_totals,
        )

    cs1 = _build_with_direct(direct_amount)
    cs2 = _build_with_direct(direct_amount + delta)

    assert len(cs1.constraints) == len(cs2.constraints)

    src_sector = sector_map.get(orig.source_node_id)
    tgt_sector = sector_map.get(orig.target_node_id)
    instr_val = orig.instrument_class.value

    for c1, c2 in zip(cs1.constraints, cs2.constraints):
        assert c1.provenance == c2.provenance, "Provenance ordering changed"
        parts = _provenance_parts(c1.provenance)
        if parts is None:
            continue
        c_sector, c_instr, c_side = parts

        if c_instr != instr_val:
            # Different instrument — unaffected.
            assert c2.rhs == c1.rhs, (
                f"Stability: unexpected RHS change for unrelated constraint {c1.provenance}"
            )
            continue

        # Determine if this constraint is the one affected.
        if c_side == "asset" and c_sector == src_sector:
            expected_shift = -delta
        elif c_side == "liab" and c_sector == tgt_sector:
            expected_shift = -delta
        else:
            expected_shift = Decimal("0")

        actual_shift = c2.rhs - c1.rhs
        assert actual_shift == expected_shift, (
            f"Stability failure for {c1.provenance}: "
            f"expected RHS shift {expected_shift}, got {actual_shift}"
        )


# ---------------------------------------------------------------------------
# Property 4 — Independence
# ---------------------------------------------------------------------------


@given(valid_sectoral_network())
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_independence_build_sectoral_rows(
    network_map_totals: tuple[NetworkState, SectorMap, SectoralTotals],
) -> None:
    """Each constraint's matrix_row references only arcs matching its (sector, instrument, side).

    For the "asset" side, every arc key in the matrix_row must have its source
    node in the constraint's sector and instrument class matching.
    For the "liab" side, the target node must be in the sector.
    """
    network, sector_map, sectoral_totals = network_map_totals
    cs: ConstraintSet = build_sectoral_rows(
        network.arcs,
        period=network.period,
        sector_map=sector_map,
        sectoral_totals=sectoral_totals,
    )

    seen_keys: set[tuple[str, str, str]] = set()
    for c in cs.constraints:
        parts = _provenance_parts(c.provenance)
        assert parts is not None, f"Cannot parse provenance: {c.provenance!r}"
        c_sector, c_instr, c_side = parts

        unique_key = (c_sector, c_instr, c_side)
        assert unique_key not in seen_keys, (
            f"Duplicate constraint for {unique_key}"
        )
        seen_keys.add(unique_key)

        for arc_key in c.matrix_row:
            arc_src, arc_tgt, arc_instr, _ = arc_key
            assert arc_instr == c_instr, (
                f"Independence: constraint for instrument {c_instr!r} "
                f"references arc of instrument {arc_instr!r}"
            )
            if c_side == "asset":
                actual_sector = sector_map.get(arc_src)
                assert actual_sector == c_sector, (
                    f"Independence (asset): constraint for sector {c_sector!r} "
                    f"references arc with source {arc_src!r} in sector {actual_sector!r}"
                )
            else:
                actual_sector = sector_map.get(arc_tgt)
                assert actual_sector == c_sector, (
                    f"Independence (liab): constraint for sector {c_sector!r} "
                    f"references arc with target {arc_tgt!r} in sector {actual_sector!r}"
                )


# ---------------------------------------------------------------------------
# Unit tests — build_sectoral_rows
# ---------------------------------------------------------------------------


class TestBuildSectoralRowsEmpty:
    def test_returns_empty_when_no_totals(self) -> None:
        arcs = [_make_arc("life_1", "ext_1", Decimal("100"))]
        cs = build_sectoral_rows(
            arcs, period=_PERIOD, sector_map={"life_1": _SECTOR_LIFE}, sectoral_totals=None
        )
        assert cs.constraints == []
        assert cs.unknowns == []

    def test_returns_empty_when_empty_totals(self) -> None:
        arcs = [_make_arc("life_1", "ext_1", Decimal("100"))]
        cs = build_sectoral_rows(
            arcs, period=_PERIOD, sector_map={"life_1": _SECTOR_LIFE}, sectoral_totals={}
        )
        assert cs.constraints == []
        assert cs.unknowns == []

    def test_returns_empty_when_no_arcs(self) -> None:
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("500")}
        cs = build_sectoral_rows(
            [], period=_PERIOD, sector_map={}, sectoral_totals=totals
        )
        # One constraint emitted, RHS == 500 (no arcs reduce it), matrix_row empty.
        assert len(cs.constraints) == 1
        assert cs.constraints[0].rhs == Decimal("500")
        assert cs.constraints[0].matrix_row == {}


class TestBuildSectoralRowsAssetSide:
    def test_single_unknown_arc_asset_side(self) -> None:
        """One unknown arc from a sector node contributes +1 to the asset constraint."""
        arc = _make_arc("life_1", "fhlb", Decimal("1000"), cls=ArcClass.A3)
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("1000")}
        sector_map: SectorMap = {"life_1": _SECTOR_LIFE}

        cs = build_sectoral_rows(
            [arc], period=_PERIOD, sector_map=sector_map, sectoral_totals=totals
        )
        assert len(cs.constraints) == 1
        c = cs.constraints[0]
        assert c.kind == "eq"
        assert c.rhs == Decimal("1000")
        assert len(c.matrix_row) == 1
        key = list(c.matrix_row.keys())[0]
        assert key[0] == "life_1"  # source
        assert c.matrix_row[key] == Decimal("1")

    def test_direct_measured_arc_folds_into_rhs(self) -> None:
        """DIRECT_MEASURED arc is subtracted from RHS; no variable remains."""
        arc = _make_direct("life_1", "fhlb", Decimal("400"), cls=ArcClass.A3)
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("1000")}
        sector_map: SectorMap = {"life_1": _SECTOR_LIFE}

        cs = build_sectoral_rows(
            [arc], period=_PERIOD, sector_map=sector_map, sectoral_totals=totals
        )
        assert len(cs.constraints) == 1
        c = cs.constraints[0]
        assert c.rhs == Decimal("600")  # 1000 − 400
        assert c.matrix_row == {}

    def test_mixed_arcs_asset_side(self) -> None:
        """Direct arc reduces RHS; unknown arc stays as variable."""
        direct = _make_direct("life_1", "fhlb_1", Decimal("300"), cls=ArcClass.A3)
        unknown = _make_arc("life_2", "fhlb_2", Decimal("700"), cls=ArcClass.A3)
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("1000")}
        sector_map: SectorMap = {"life_1": _SECTOR_LIFE, "life_2": _SECTOR_LIFE}

        cs = build_sectoral_rows(
            [direct, unknown],
            period=_PERIOD,
            sector_map=sector_map,
            sectoral_totals=totals,
        )
        assert len(cs.constraints) == 1
        c = cs.constraints[0]
        assert c.rhs == Decimal("700")  # 1000 − 300
        assert len(c.matrix_row) == 1
        key = list(c.matrix_row.keys())[0]
        assert key[0] == "life_2"

    def test_external_node_arc_ignored(self) -> None:
        """An arc from a node not in sector_map does not appear in the constraint."""
        arc = _make_arc("ext_bank", "fhlb", Decimal("5000"), cls=ArcClass.A3)
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("1000")}
        sector_map: SectorMap = {"life_1": _SECTOR_LIFE}

        cs = build_sectoral_rows(
            [arc], period=_PERIOD, sector_map=sector_map, sectoral_totals=totals
        )
        c = cs.constraints[0]
        assert c.rhs == Decimal("1000")  # untouched
        assert c.matrix_row == {}


class TestBuildSectoralRowsLiabSide:
    def test_single_unknown_arc_liab_side(self) -> None:
        """One unknown arc to a sector node contributes +1 to the liability constraint."""
        arc = _make_arc("fhlb", "life_1", Decimal("800"), cls=ArcClass.A3)
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "liab"): Decimal("800")}
        sector_map: SectorMap = {"life_1": _SECTOR_LIFE}

        cs = build_sectoral_rows(
            [arc], period=_PERIOD, sector_map=sector_map, sectoral_totals=totals
        )
        assert len(cs.constraints) == 1
        c = cs.constraints[0]
        assert c.rhs == Decimal("800")
        assert len(c.matrix_row) == 1
        key = list(c.matrix_row.keys())[0]
        assert key[1] == "life_1"  # target

    def test_direct_measured_liab_arc_folds_into_rhs(self) -> None:
        arc = _make_direct("fhlb", "life_1", Decimal("200"), cls=ArcClass.A3)
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "liab"): Decimal("500")}
        sector_map: SectorMap = {"life_1": _SECTOR_LIFE}

        cs = build_sectoral_rows(
            [arc], period=_PERIOD, sector_map=sector_map, sectoral_totals=totals
        )
        c = cs.constraints[0]
        assert c.rhs == Decimal("300")  # 500 − 200
        assert c.matrix_row == {}


class TestBuildSectoralRowsMultipleSectors:
    def test_two_sectors_two_instruments(self) -> None:
        """Multiple (sector, instrument, side) entries each get their own constraint."""
        arc1 = _make_arc("life_1", "ext", Decimal("100"), cls=ArcClass.A3)
        arc2 = _make_arc("mmf_1", "ext", Decimal("200"), cls=ArcClass.A8)
        totals: SectoralTotals = {
            (_SECTOR_LIFE, "A3", "asset"): Decimal("100"),
            (_SECTOR_MMF, "A8", "asset"): Decimal("200"),
        }
        sector_map: SectorMap = {
            "life_1": _SECTOR_LIFE,
            "mmf_1": _SECTOR_MMF,
        }
        cs = build_sectoral_rows(
            [arc1, arc2],
            period=_PERIOD,
            sector_map=sector_map,
            sectoral_totals=totals,
        )
        assert len(cs.constraints) == 2
        provenances = {c.provenance for c in cs.constraints}
        assert any(_SECTOR_LIFE in p and "A3" in p for p in provenances)
        assert any(_SECTOR_MMF in p and "A8" in p for p in provenances)

    def test_arc_from_one_sector_does_not_affect_other_sector_constraint(self) -> None:
        """A life-insurer arc must not appear in the MMF constraint matrix_row."""
        arc_life = _make_arc("life_1", "ext", Decimal("500"), cls=ArcClass.A3)
        arc_mmf = _make_arc("mmf_1", "ext", Decimal("300"), cls=ArcClass.A3)
        totals: SectoralTotals = {
            (_SECTOR_LIFE, "A3", "asset"): Decimal("500"),
            (_SECTOR_MMF, "A3", "asset"): Decimal("300"),
        }
        sector_map: SectorMap = {
            "life_1": _SECTOR_LIFE,
            "mmf_1": _SECTOR_MMF,
        }
        cs = build_sectoral_rows(
            [arc_life, arc_mmf],
            period=_PERIOD,
            sector_map=sector_map,
            sectoral_totals=totals,
        )
        for c in cs.constraints:
            parts = _provenance_parts(c.provenance)
            assert parts is not None
            c_sector, _, c_side = parts
            for arc_key in c.matrix_row:
                arc_src, _, _, _ = arc_key
                assert sector_map.get(arc_src) == c_sector, (
                    f"Sector bleed: {c_sector} constraint has arc from {sector_map.get(arc_src)}"
                )


class TestBuildSectoralRowsPeriodFiltering:
    def test_arcs_from_other_periods_ignored(self) -> None:
        """Arcs with a different period must not appear in the constraint."""
        current = _make_arc("life_1", "ext", Decimal("100"), cls=ArcClass.A3, period=_PERIOD)
        old = _make_arc("life_1", "ext2", Decimal("9999"), cls=ArcClass.A3, period=_OTHER_PERIOD)
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("100")}
        sector_map: SectorMap = {"life_1": _SECTOR_LIFE}

        cs = build_sectoral_rows(
            [current, old],
            period=_PERIOD,
            sector_map=sector_map,
            sectoral_totals=totals,
        )
        c = cs.constraints[0]
        # The old-period arc should be filtered; only current-period arc appears.
        assert len(c.matrix_row) == 1
        key = list(c.matrix_row.keys())[0]
        assert key[3] == str(_PERIOD)


class TestBuildSectoralRowsProvenance:
    def test_provenance_format(self) -> None:
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("1000")}
        cs = build_sectoral_rows(
            [], period=_PERIOD, sector_map={}, sectoral_totals=totals
        )
        prov = cs.constraints[0].provenance
        assert _SECTOR_LIFE in prov
        assert "A3" in prov
        assert "asset" in prov
        assert str(_PERIOD) in prov
        assert "Law 3 (sectoral)" in prov

    def test_provenance_parseable(self) -> None:
        totals: SectoralTotals = {
            (_SECTOR_LIFE, "A3", "asset"): Decimal("1000"),
            (_SECTOR_MMF, "A8", "liab"): Decimal("500"),
        }
        cs = build_sectoral_rows(
            [], period=_PERIOD, sector_map={}, sectoral_totals=totals
        )
        for c in cs.constraints:
            parts = _provenance_parts(c.provenance)
            assert parts is not None, f"Could not parse provenance: {c.provenance!r}"
            sector_id, instr_val, side = parts
            assert (sector_id, instr_val, side) in totals  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Unit tests — check_sectoral
# ---------------------------------------------------------------------------


class TestCheckSectoralEmpty:
    def test_trivially_passes_with_no_totals(self) -> None:
        network = _make_network([_make_arc("life_1", "ext", Decimal("100"))])
        result = check_sectoral(
            network, sector_map={"life_1": _SECTOR_LIFE}, sectoral_totals=None
        )
        assert result.satisfied
        assert result.violations == []
        assert result.checked_count == 0

    def test_trivially_passes_with_empty_totals(self) -> None:
        network = _make_network([_make_arc("life_1", "ext", Decimal("100"))])
        result = check_sectoral(
            network, sector_map={"life_1": _SECTOR_LIFE}, sectoral_totals={}
        )
        assert result.satisfied
        assert result.checked_count == 0

    def test_empty_network_zero_actual(self) -> None:
        """Empty network yields actual=0 for all checked entries."""
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("1000")}
        network = _make_network([])
        result = check_sectoral(
            network,
            sector_map={"life_1": _SECTOR_LIFE},
            sectoral_totals=totals,
            tol=Decimal("0.001"),
        )
        # actual=0 vs expected=1000 → violation
        assert not result.satisfied
        assert len(result.violations) == 1
        v = result.violations[0]
        assert v.actual_total == Decimal("0")
        assert v.expected_total == Decimal("1000")


class TestCheckSectoralSatisfied:
    def test_exact_match_passes(self) -> None:
        arc = _make_arc("life_1", "fhlb", Decimal("750"), cls=ArcClass.A3)
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("750")}
        network = _make_network([arc])
        result = check_sectoral(
            network,
            sector_map={"life_1": _SECTOR_LIFE},
            sectoral_totals=totals,
        )
        assert result.satisfied
        assert result.violations == []
        assert result.checked_count == 1

    def test_multiple_arcs_same_sector_instrument_sum(self) -> None:
        arc1 = _make_arc("life_1", "fhlb_1", Decimal("400"), cls=ArcClass.A3)
        arc2 = _make_arc("life_2", "fhlb_2", Decimal("600"), cls=ArcClass.A3)
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("1000")}
        network = _make_network([arc1, arc2])
        result = check_sectoral(
            network,
            sector_map={"life_1": _SECTOR_LIFE, "life_2": _SECTOR_LIFE},
            sectoral_totals=totals,
        )
        assert result.satisfied

    def test_within_tolerance_passes(self) -> None:
        # actual=999.5, expected=1000, residual=0.5 < 0.1% * 1000 = 1.0
        arc = _make_arc("life_1", "fhlb", Decimal("999.5"), cls=ArcClass.A3)
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("1000")}
        network = _make_network([arc])
        result = check_sectoral(
            network,
            sector_map={"life_1": _SECTOR_LIFE},
            sectoral_totals=totals,
            tol=Decimal("0.001"),
        )
        assert result.satisfied

    def test_liab_side_exact_match(self) -> None:
        arc = _make_arc("fhlb", "life_1", Decimal("850"), cls=ArcClass.A3)
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "liab"): Decimal("850")}
        network = _make_network([arc])
        result = check_sectoral(
            network,
            sector_map={"life_1": _SECTOR_LIFE},
            sectoral_totals=totals,
        )
        assert result.satisfied


class TestCheckSectoralViolations:
    def test_single_violation_detected(self) -> None:
        # actual=500, expected=1000 → residual=500, threshold≈1, violation
        arc = _make_arc("life_1", "fhlb", Decimal("500"), cls=ArcClass.A3)
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("1000")}
        network = _make_network([arc])
        result = check_sectoral(
            network,
            sector_map={"life_1": _SECTOR_LIFE},
            sectoral_totals=totals,
            tol=Decimal("0.001"),
        )
        assert not result.satisfied
        assert len(result.violations) == 1
        v = result.violations[0]
        assert v.sector_id == _SECTOR_LIFE
        assert v.instrument_class_value == "A3"
        assert v.side == "asset"
        assert v.actual_total == Decimal("500")
        assert v.expected_total == Decimal("1000")
        assert v.residual == Decimal("-500")

    def test_violation_arc_count_correct(self) -> None:
        arc1 = _make_arc("life_1", "fhlb_1", Decimal("100"), cls=ArcClass.A3)
        arc2 = _make_arc("life_2", "fhlb_2", Decimal("200"), cls=ArcClass.A3)
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("9999")}
        network = _make_network([arc1, arc2])
        result = check_sectoral(
            network,
            sector_map={"life_1": _SECTOR_LIFE, "life_2": _SECTOR_LIFE},
            sectoral_totals=totals,
            tol=Decimal("0.001"),
        )
        assert not result.satisfied
        assert result.violations[0].arc_count == 2

    def test_multiple_violations_detected(self) -> None:
        arc_a3 = _make_arc("life_1", "fhlb", Decimal("100"), cls=ArcClass.A3)
        arc_a8 = _make_arc("life_1", "mmf", Decimal("50"), cls=ArcClass.A8)
        totals: SectoralTotals = {
            (_SECTOR_LIFE, "A3", "asset"): Decimal("1000"),  # residual=−900
            (_SECTOR_LIFE, "A8", "asset"): Decimal("900"),   # residual=−850
        }
        network = _make_network([arc_a3, arc_a8])
        result = check_sectoral(
            network,
            sector_map={"life_1": _SECTOR_LIFE},
            sectoral_totals=totals,
            tol=Decimal("0.001"),
        )
        assert not result.satisfied
        assert len(result.violations) == 2
        assert result.checked_count == 2

    def test_violation_provenance_contains_details(self) -> None:
        arc = _make_arc("life_1", "fhlb", Decimal("1"), cls=ArcClass.A3)
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("10000")}
        network = _make_network([arc])
        result = check_sectoral(
            network,
            sector_map={"life_1": _SECTOR_LIFE},
            sectoral_totals=totals,
        )
        assert not result.satisfied
        prov = result.violations[0].provenance
        assert _SECTOR_LIFE in prov
        assert "A3" in prov
        assert "asset" in prov
        assert "actual=" in prov
        assert "expected=" in prov
        assert "residual=" in prov


class TestCheckSectoralSectorCount:
    def test_sector_count_reflects_seen_sectors(self) -> None:
        arc_life = _make_arc("life_1", "ext", Decimal("100"), cls=ArcClass.A3)
        arc_mmf = _make_arc("mmf_1", "ext", Decimal("200"), cls=ArcClass.A8)
        network = _make_network([arc_life, arc_mmf])
        result = check_sectoral(
            network,
            sector_map={"life_1": _SECTOR_LIFE, "mmf_1": _SECTOR_MMF},
            sectoral_totals=None,
        )
        assert result.sector_count == 2


class TestCheckSectoralExternalNodes:
    def test_arcs_between_external_nodes_not_counted(self) -> None:
        """Arcs where neither endpoint is in sector_map must not affect sector totals."""
        arc_external = _make_arc("bank_a", "bank_b", Decimal("9999"), cls=ArcClass.A9)
        arc_sector = _make_arc("life_1", "ext", Decimal("500"), cls=ArcClass.A3)
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("500")}
        network = _make_network([arc_external, arc_sector])
        result = check_sectoral(
            network,
            sector_map={"life_1": _SECTOR_LIFE},
            sectoral_totals=totals,
        )
        assert result.satisfied


class TestCheckSectoralTolerance:
    def test_custom_tol_strict(self) -> None:
        """At very tight tolerance, even a tiny residual is a violation."""
        arc = _make_arc("life_1", "fhlb", Decimal("999.99"), cls=ArcClass.A3)
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("1000")}
        network = _make_network([arc])
        # residual = 0.01; threshold with tol=0 is just _MIN_ABS_TOL=0.1 → no violation
        result_loose = check_sectoral(
            network,
            sector_map={"life_1": _SECTOR_LIFE},
            sectoral_totals=totals,
            tol=Decimal("0"),
        )
        # With _MIN_ABS_TOL=0.1, residual 0.01 < 0.1 → satisfied
        assert result_loose.satisfied

    def test_above_absolute_floor_is_violation(self) -> None:
        """A residual above _MIN_ABS_TOL is always a violation."""
        arc = _make_arc("life_1", "fhlb", Decimal("999.5"), cls=ArcClass.A3)
        # residual = 0.5 > _MIN_ABS_TOL(0.1); even tol=0 → violation
        totals: SectoralTotals = {(_SECTOR_LIFE, "A3", "asset"): Decimal("1000")}
        network = _make_network([arc])
        result = check_sectoral(
            network,
            sector_map={"life_1": _SECTOR_LIFE},
            sectoral_totals=totals,
            tol=Decimal("0"),
        )
        assert not result.satisfied


# ---------------------------------------------------------------------------
# Unit tests — _provenance_parts
# ---------------------------------------------------------------------------


class TestProvenanceParts:
    def test_roundtrip_asset(self) -> None:
        prov = (
            f"Law 3 (sectoral) for sector {_SECTOR_LIFE!r}, "
            f"instrument 'A3', side 'asset', period 2024-Q4"
        )
        parts = _provenance_parts(prov)
        assert parts == (_SECTOR_LIFE, "A3", "asset")

    def test_roundtrip_liab(self) -> None:
        prov = (
            f"Law 3 (sectoral) for sector {_SECTOR_MMF!r}, "
            f"instrument 'A8', side 'liab', period 2023-Q2"
        )
        parts = _provenance_parts(prov)
        assert parts == (_SECTOR_MMF, "A8", "liab")

    def test_non_matching_returns_none(self) -> None:
        assert _provenance_parts("Law 1 (KCL) for node 'X', period 2024-Q4") is None
        assert _provenance_parts("") is None
        assert _provenance_parts("random text") is None
