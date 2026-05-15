"""Law 3 — Z.1 sectoral aggregate constraints (project plan §1.1).

For every sector *s* and instrument *k* where the Federal Reserve Z.1 release
publishes an aggregate, two equalities are enforced:

.. math::

    \\sum_{i \\in s,\\, j \\in V} x_{ij}^{k}(t) &= Z^{\\text{asset}}_{s,k}(t)
    \\quad \\text{(sector holds instrument)}\\\\
    \\sum_{j \\in s,\\, i \\in V} x_{ij}^{k}(t) &= Z^{\\text{liab}}_{s,k}(t)
    \\quad \\text{(sector issues instrument)}

These are the **upper-level Kirchhoff equations** of the conservation-circuit
framing: the aggregated sector must match the Z.1 boundary conditions exactly
within Z.1's published precision.

Source tables (per project plan §10.1):
- L.116 — U.S. life insurance companies
- L.121 — P&C insurers
- L.207–L.208 — Depository institutions
- L.211 — ABS issuers
- L.226–L.227 — Repo / sec-lending aggregates

The sector membership of each network node is supplied by the caller as a
``SectorMap`` (node_id → sector_id string).  The expected sectoral totals are
supplied as a ``SectoralTotals`` mapping derived from Z.1 data, typically
produced by :class:`~claimweb.fetchers.z1.Z1Fetcher`.

``DIRECT_MEASURED`` arcs are folded into the right-hand side as constants;
all other arcs remain as variables in the constraint matrix.

Public interface
----------------
``SectorMap``
    Mapping from node_id to sector_id.
``SectoralTotals``
    Mapping from *(sector_id, instrument_class_value, side)* to the Z.1
    expected total in millions USD.
``SectoralViolation``
    One *(sector, instrument, side)* triple that violates Law 3.
``SectoralResult``
    Aggregate result of :func:`check_sectoral`.
``build_sectoral_rows``
    Compile one :class:`~claimweb.constraints.kcl.LinearConstraint` per
    *(sector, instrument, side)* entry in *sectoral_totals*.
``check_sectoral``
    Directly verify Law 3 on a concrete
    :class:`~claimweb.constraints.kcl.NetworkState`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from claimweb.constraints.kcl import (
    _ZERO,
    ArcKey,
    ConstraintSet,
    LinearConstraint,
    NetworkState,
    _group_arcs_by_key_with_flag,
)
from claimweb.fetchers.base import ArcFact, DataQualityFlag, Period

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

#: Mapping from node_id to sector_id string (e.g. "sector:life_insurance_companies").
SectorMap = dict[str, str]

#: Mapping from (sector_id, instrument_class_value, side) → expected total in
#: millions USD.  "asset" means the sector holds the instrument (outgoing arc
#: from a sector node); "liab" means the sector issues the instrument (incoming
#: arc to a sector node).
SectoralTotals = dict[tuple[str, str, Literal["asset", "liab"]], Decimal]

# Relative tolerance: 0.1 % is tighter than Z.1's inherent one-decimal-place-
# in-billions rounding (~0.05 %) for typical sector aggregates, and appropriate
# for constraint enforcement on solved networks.
_DEFAULT_TOL_REL = Decimal("0.001")

# Absolute floor: $0.1 M prevents spurious violations on tiny test networks.
_MIN_ABS_TOL = Decimal("0.1")

_ONE = Decimal("1")

# Regex to extract (sector_id, instrument_class_value, side) from a provenance string.
_PROV_RE = re.compile(
    r"Law 3 \(sectoral\) for sector '([^']+)', instrument '([^']+)', "
    r"side '([^']+)', period"
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class SectoralViolation:
    """One *(sector, instrument, side)* triple that violates Law 3."""

    sector_id: str
    instrument_class_value: str
    side: Literal["asset", "liab"]
    period: Period
    actual_total: Decimal    # sum of arcs actually present in the network
    expected_total: Decimal  # Z.1 published value
    residual: Decimal        # actual_total − expected_total (signed)
    arc_count: int           # number of arcs that contribute to actual_total
    provenance: str


@dataclass
class SectoralResult:
    """Aggregate result of :func:`check_sectoral` on a :class:`~claimweb.constraints.kcl.NetworkState`."""

    period: Period
    satisfied: bool
    violations: list[SectoralViolation]
    sector_count: int  # distinct sectors seen in the network's arcs + sector_map
    checked_count: int  # (sector, instrument, side) tuples checked


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _provenance_parts(provenance: str) -> tuple[str, str, str] | None:
    """Extract *(sector_id, instrument_class_value, side)* from a provenance string."""
    m = _PROV_RE.search(provenance)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_sectoral_rows(
    facts: list[ArcFact],
    *,
    period: Period,
    sector_map: SectorMap,
    sectoral_totals: SectoralTotals | None = None,
) -> ConstraintSet:
    """Compile one :class:`~claimweb.constraints.kcl.LinearConstraint` per
    *(sector, instrument, side)* entry in *sectoral_totals*.

    For the **asset side** of sector *s* and instrument *k*, the equality is:

    .. math::

        \\sum_{\\text{unknown arcs: src} \\in s, \\text{instr}=k} x
        = Z^{\\text{asset}}_{s,k} - \\sum_{\\text{direct-measured arcs:
          src} \\in s, \\text{instr}=k} x

    For the **liability side**, the equality is:

    .. math::

        \\sum_{\\text{unknown arcs: tgt} \\in s, \\text{instr}=k} x
        = Z^{\\text{liab}}_{s,k} - \\sum_{\\text{direct-measured arcs:
          tgt} \\in s, \\text{instr}=k} x

    ``DIRECT_MEASURED`` arcs are folded into the right-hand side as constants.
    All other arcs remain as variables in
    :attr:`~claimweb.constraints.kcl.LinearConstraint.matrix_row`.

    When *sectoral_totals* is ``None`` or empty, an empty
    :class:`~claimweb.constraints.kcl.ConstraintSet` is returned.

    Parameters
    ----------
    facts:
        All :class:`~claimweb.fetchers.base.ArcFact`\\s available; arcs with
        a period other than *period* are silently filtered out.
    period:
        The period to constrain.
    sector_map:
        Mapping from node_id to sector_id string.  Nodes absent from the map
        are treated as not belonging to any sector and are ignored by all
        sectoral constraints.
    sectoral_totals:
        Mapping from *(sector_id, instrument_class_value, side)* to the Z.1
        expected total in millions USD.  ``None`` or empty → no constraints
        emitted.

    Returns
    -------
    ConstraintSet
        One :class:`~claimweb.constraints.kcl.LinearConstraint` per entry in
        *sectoral_totals* (sorted by key), plus the list of all unknown
        :class:`~claimweb.constraints.kcl.ArcKey`\\s referenced.
    """
    if not sectoral_totals:
        return ConstraintSet(constraints=[], unknowns=[])

    period_str = str(period)
    arc_data = _group_arcs_by_key_with_flag(facts, period)

    constraints: list[LinearConstraint] = []
    all_unknowns: set[ArcKey] = set()

    for key in sorted(sectoral_totals):
        sector_id, instr_val, side = key
        total = sectoral_totals[key]

        # RHS starts as the Z.1 published total; direct-measured arcs reduce it.
        rhs = total
        matrix_row: dict[ArcKey, Decimal] = {}

        for arc_key, (amount, flag) in arc_data.items():
            arc_src, arc_tgt, arc_instr, _ = arc_key

            if arc_instr != instr_val:
                continue

            # Determine whether this arc contributes to the (sector, side) sum.
            if side == "asset":
                in_sector = sector_map.get(arc_src) == sector_id
            else:
                in_sector = sector_map.get(arc_tgt) == sector_id

            if not in_sector:
                continue

            if flag == DataQualityFlag.DIRECT_MEASURED:
                # Known constant: fold into RHS so solver sees net unknown portion.
                rhs -= amount
            else:
                matrix_row[arc_key] = matrix_row.get(arc_key, _ZERO) + _ONE
                all_unknowns.add(arc_key)

        constraints.append(
            LinearConstraint(
                matrix_row=matrix_row,
                rhs=rhs,
                kind="eq",
                provenance=(
                    f"Law 3 (sectoral) for sector {sector_id!r}, "
                    f"instrument {instr_val!r}, side {side!r}, period {period_str}"
                ),
            )
        )

    return ConstraintSet(
        constraints=constraints,
        unknowns=sorted(all_unknowns),
    )


def check_sectoral(
    network: NetworkState,
    *,
    sector_map: SectorMap,
    sectoral_totals: SectoralTotals | None = None,
    tol: Decimal = _DEFAULT_TOL_REL,
) -> SectoralResult:
    """Verify that Law 3 holds for each *(sector, instrument, side)* tuple in
    a solved (concrete) network.

    For each tuple in *sectoral_totals*, the residual is:

    .. math::

        r = \\left|
            \\sum_{\\text{matching arcs}} x - Z_{s,k}^{\\text{asset/liab}}
        \\right|

    A violation is reported when:

    .. math::

        r > \\max\\bigl(
            \\text{tol} \\times |Z_{s,k}|,\\; 0.1
        \\bigr)

    When *sectoral_totals* is ``None`` or empty, the check trivially passes
    (no external reference to compare against); ``checked_count == 0``.

    Parameters
    ----------
    network:
        Concrete, solved network whose arc values are all populated.
        :class:`~claimweb.constraints.kcl.NetworkState` guarantees all arcs
        belong to ``network.period``.
    sector_map:
        Mapping from node_id to sector_id.
    sectoral_totals:
        Expected Z.1 aggregate per *(sector_id, instrument_class_value, side)*
        in millions USD.  Absent → check trivially passes.
    tol:
        Relative tolerance as a fraction of the expected total.
        Default ``0.001`` (0.1 %).

    Returns
    -------
    SectoralResult
        Summary of which *(sector, instrument, side)* tuples (if any) violate
        Law 3.
    """
    period = network.period
    period_str = str(period)

    # Tally arc amounts by (sector_id, instr_val, side) across the network.
    # NetworkState.__post_init__ guarantees all arcs are for network.period.
    tally_totals: dict[tuple[str, str, str], Decimal] = {}
    tally_counts: dict[tuple[str, str, str], int] = {}

    for arc in network.arcs:
        instr_val = arc.instrument_class.value
        amount = arc.dollar_amount_millions

        src_sector = sector_map.get(arc.source_node_id)
        if src_sector is not None:
            k = (src_sector, instr_val, "asset")
            tally_totals[k] = tally_totals.get(k, _ZERO) + amount
            tally_counts[k] = tally_counts.get(k, 0) + 1

        tgt_sector = sector_map.get(arc.target_node_id)
        if tgt_sector is not None:
            k = (tgt_sector, instr_val, "liab")
            tally_totals[k] = tally_totals.get(k, _ZERO) + amount
            tally_counts[k] = tally_counts.get(k, 0) + 1

    distinct_sectors = len({s for s, _, _ in tally_totals})

    if not sectoral_totals:
        return SectoralResult(
            period=period,
            satisfied=True,
            violations=[],
            sector_count=distinct_sectors,
            checked_count=0,
        )

    violations: list[SectoralViolation] = []
    checked = 0

    for key in sorted(sectoral_totals):
        sector_id, instr_val, side = key
        expected = sectoral_totals[key]
        k = (sector_id, instr_val, side)
        actual = tally_totals.get(k, _ZERO)
        arc_count = tally_counts.get(k, 0)
        residual = actual - expected
        threshold = max(tol * abs(expected), _MIN_ABS_TOL)

        if abs(residual) > threshold:
            violations.append(
                SectoralViolation(
                    sector_id=sector_id,
                    instrument_class_value=instr_val,
                    side=side,
                    period=period,
                    actual_total=actual,
                    expected_total=expected,
                    residual=residual,
                    arc_count=arc_count,
                    provenance=(
                        f"Law 3 (sectoral) for sector {sector_id!r}, "
                        f"instrument {instr_val!r}, side {side!r}, "
                        f"period {period_str}: "
                        f"actual={actual}, expected={expected}, residual={residual}"
                    ),
                )
            )

        checked += 1

    return SectoralResult(
        period=period,
        satisfied=len(violations) == 0,
        violations=violations,
        sector_count=distinct_sectors,
        checked_count=checked,
    )
