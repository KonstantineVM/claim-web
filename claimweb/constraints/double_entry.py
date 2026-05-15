"""Law 2 — Double-entry consistency per instrument (project plan §1.1).

For every instrument *k* and period *t*, total holdings by parties in *V*
equal total issuances by parties in *V* within the boundary term :math:`b_k`:

.. math::

    \\sum_{i,j \\in V} x_{ij}^{k}(t)
    = b_k(t)
    + \\sum_{\\text{DIRECT\\_MEASURED arcs of }k} x_{ij}^k(t)

When the network boundary is closed (:math:`b_k = 0` and all parties are
in *V*), the constraint is trivially satisfied and no rows are emitted.
When an external aggregate total is known (from Z.1, FHLB Office of Finance,
or FABS data), the total constrains the sum of unknown arc variables.

The public API mirrors the KCL module (Law 1): a row-builder for the sparse
linear constraint system consumed by :mod:`claimweb.reconstruct.solver`, and
a direct checker for validating concrete solved networks.

Public interface
----------------
``InstrumentTotals``
    Mapping from ``ArcClass.value`` string (e.g., ``"A3"``) to the known
    aggregate total in millions USD (the boundary term).  Typically sourced
    from Z.1 sectoral data or FHLB Office of Finance aggregate reports.
``DoubleEntryViolation``
    One instrument that violates Law 2 in a concrete solved network.
``DoubleEntryResult``
    Aggregate result of :func:`check_double_entry`.
``build_double_entry_rows``
    Compile one :class:`~claimweb.constraints.kcl.LinearConstraint` per
    instrument where a boundary total is known.
``check_double_entry``
    Directly verify Law 2 on a concrete
    :class:`~claimweb.constraints.kcl.NetworkState`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

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

#: Mapping from ArcClass.value (e.g., ``"A3"``) to the expected aggregate
#: total in millions USD.  Supplied by the caller from Z.1 or FHLB data.
InstrumentTotals = dict[str, Decimal]

# Relative tolerance: 0.5 % per conservation-laws rule for double-entry.
_DEFAULT_TOL_REL = Decimal("0.005")

# Absolute floor: $0.1 M — avoids spurious violations on tiny test networks.
_MIN_ABS_TOL = Decimal("0.1")

# Pattern used to extract instrument class value from a provenance string.
_PROV_RE = re.compile(r"Law 2 \(double-entry\) for instrument '([^']+)', period")

_ONE = Decimal("1")


@dataclass
class DoubleEntryViolation:
    """One instrument that violates the double-entry law in a concrete network."""

    instrument_class_value: str   # e.g. "A3"
    period: Period
    actual_total: Decimal         # sum of all arc amounts for this instrument
    expected_total: Decimal       # boundary_terms value for this instrument
    residual: Decimal             # actual_total - expected_total (signed)
    arc_count: int                # number of arcs contributing to actual_total
    provenance: str


@dataclass
class DoubleEntryResult:
    """Aggregate result of :func:`check_double_entry` on a :class:`~claimweb.constraints.kcl.NetworkState`."""

    period: Period
    satisfied: bool
    violations: list[DoubleEntryViolation]
    instrument_count: int    # distinct instruments present in the network
    checked_count: int       # instruments checked against a boundary term


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _provenance_instrument(provenance: str) -> str | None:
    """Extract the instrument class value embedded in a double-entry provenance string."""
    m = _PROV_RE.search(provenance)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_double_entry_rows(
    facts: list[ArcFact],
    *,
    period: Period,
    boundary_terms: InstrumentTotals | None = None,
) -> ConstraintSet:
    """Compile one :class:`~claimweb.constraints.kcl.LinearConstraint` per
    instrument that has a known aggregate total (boundary term).

    For each instrument *k* in *boundary_terms*, the generated equality is:

    .. math::

        \\sum_{\\text{unknown arcs of }k} x_{ij}^k
        = b_k - \\sum_{\\text{direct-measured arcs of }k} x_{ij}^k

    ``DIRECT_MEASURED`` arcs are folded into the right-hand side as known
    constants; all other arcs remain as variables in
    :attr:`~claimweb.constraints.kcl.LinearConstraint.matrix_row`.

    When *boundary_terms* is ``None`` or empty, the law is trivially
    satisfied for a closed network (every arc is simultaneously a holding
    and an issuance) and an empty :class:`~claimweb.constraints.kcl.ConstraintSet`
    is returned.

    Parameters
    ----------
    facts:
        All :class:`~claimweb.fetchers.base.ArcFact`\\s available; arcs with
        a period other than *period* are silently filtered out.
    period:
        The period to constrain.
    boundary_terms:
        Mapping from ``ArcClass.value`` (e.g., ``"A3"``) to the expected
        total outstanding for that instrument in millions USD.  Typically
        sourced from Z.1 or FHLB Office of Finance aggregate reports.
        ``None`` or empty dict → no constraints emitted.

    Returns
    -------
    ConstraintSet
        One :class:`~claimweb.constraints.kcl.LinearConstraint` per
        instrument in *boundary_terms* (sorted by instrument key), plus the
        list of all unknown :class:`~claimweb.constraints.kcl.ArcKey`\\s
        referenced.
    """
    if not boundary_terms:
        return ConstraintSet(constraints=[], unknowns=[])

    period_str = str(period)
    arc_data = _group_arcs_by_key_with_flag(facts, period)

    # Bucket arc data by instrument class value.
    by_instrument: dict[str, dict[ArcKey, tuple[Decimal, DataQualityFlag]]] = {}
    for key, (amount, flag) in arc_data.items():
        instr_val = key[2]  # ArcKey = (source, target, instrument_class.value, period_str)
        by_instrument.setdefault(instr_val, {})[key] = (amount, flag)

    constraints: list[LinearConstraint] = []
    all_unknowns: set[ArcKey] = set()

    for instr_val in sorted(boundary_terms):
        total = boundary_terms[instr_val]
        # RHS starts as the boundary term; known arcs are folded in below.
        rhs = total
        matrix_row: dict[ArcKey, Decimal] = {}

        for key, (amount, flag) in by_instrument.get(instr_val, {}).items():
            if flag == DataQualityFlag.DIRECT_MEASURED:
                # Known constant: subtract from RHS so unknowns account for
                # the remainder.
                rhs -= amount
            else:
                # Unknown variable: coefficient +1 (each arc contributes to
                # the instrument total with weight 1).
                matrix_row[key] = matrix_row.get(key, _ZERO) + _ONE
                all_unknowns.add(key)

        # Emit the constraint even when matrix_row is empty (all arcs are
        # directly measured): the solver then verifies 0 == rhs, which checks
        # that the measured total matches the external aggregate.
        constraints.append(
            LinearConstraint(
                matrix_row=matrix_row,
                rhs=rhs,
                kind="eq",
                provenance=(
                    f"Law 2 (double-entry) for instrument {instr_val!r}, "
                    f"period {period_str}"
                ),
            )
        )

    return ConstraintSet(
        constraints=constraints,
        unknowns=sorted(all_unknowns),
    )


def check_double_entry(
    network: NetworkState,
    *,
    boundary_terms: InstrumentTotals | None = None,
    tol: Decimal = _DEFAULT_TOL_REL,
) -> DoubleEntryResult:
    """Verify that Law 2 holds for each instrument in a solved network.

    For each instrument *k* listed in *boundary_terms*, the residual is:

    .. math::

        r_k = \\left|
            \\sum_{\\text{all arcs of }k} x_{ij}^k
            - \\text{boundary\\_terms}[k]
        \\right|

    A violation is reported when:

    .. math::

        r_k > \\max\\bigl(
            \\text{tol} \\times |\\text{boundary\\_terms}[k]|,\\;
            0.1
        \\bigr)

    When *boundary_terms* is ``None`` or empty, the law is trivially
    satisfied for a closed network (every arc is simultaneously a holding
    and an issuance); no violations are reported and ``checked_count == 0``.

    Parameters
    ----------
    network:
        Concrete, solved network whose arc values are all populated.
    boundary_terms:
        Expected aggregate total per instrument in millions USD.  When
        absent, the check trivially passes (no external reference to compare
        against).
    tol:
        Relative tolerance as a fraction of the expected total.
        Default ``0.005`` (0.5 %) per the project conservation-laws rule.

    Returns
    -------
    DoubleEntryResult
        Summary of which instruments (if any) violate Law 2.
    """
    period = network.period
    period_str = str(period)

    # Tally total arc amounts and arc counts per instrument for this period.
    # NetworkState.__post_init__ guarantees all arcs match network.period.
    instrument_totals: dict[str, Decimal] = {}
    instrument_arc_count: dict[str, int] = {}
    for arc in network.arcs:
        val = arc.instrument_class.value
        instrument_totals[val] = instrument_totals.get(val, _ZERO) + arc.dollar_amount_millions
        instrument_arc_count[val] = instrument_arc_count.get(val, 0) + 1

    distinct_instruments = len(instrument_totals)

    if not boundary_terms:
        return DoubleEntryResult(
            period=period,
            satisfied=True,
            violations=[],
            instrument_count=distinct_instruments,
            checked_count=0,
        )

    violations: list[DoubleEntryViolation] = []
    checked = 0

    for instr_val in sorted(boundary_terms):
        expected = boundary_terms[instr_val]
        actual = instrument_totals.get(instr_val, _ZERO)
        arc_count = instrument_arc_count.get(instr_val, 0)
        residual = actual - expected

        threshold = max(tol * abs(expected), _MIN_ABS_TOL)

        if abs(residual) > threshold:
            violations.append(
                DoubleEntryViolation(
                    instrument_class_value=instr_val,
                    period=period,
                    actual_total=actual,
                    expected_total=expected,
                    residual=residual,
                    arc_count=arc_count,
                    provenance=(
                        f"Law 2 (double-entry) for instrument {instr_val!r}, "
                        f"period {period_str}: "
                        f"actual={actual}, expected={expected}, residual={residual}"
                    ),
                )
            )

        checked += 1

    return DoubleEntryResult(
        period=period,
        satisfied=len(violations) == 0,
        violations=violations,
        instrument_count=distinct_instruments,
        checked_count=checked,
    )
