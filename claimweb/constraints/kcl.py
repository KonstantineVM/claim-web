"""Law 1 — Balance-sheet identity at each node (project plan §1.1).

For every node *i* and every period *t*:

.. math::

    \\sum_{j,k} x_{ij}^{k}(t) + N_i(t) = \\sum_{j,k} x_{ji}^{k}(t) + E_i(t)

where:

* :math:`x_{ij}^k`  — claim from node *i* on node *j* for instrument class *k*
  (asset of *i*, liability of *j*)
* :math:`N_i`  — non-financial assets at node *i* (real estate, PP&E; observed)
* :math:`E_i`  — equity at node *i* (residual; observed from balance-sheet totals)

Total assets equal total liabilities plus equity at every node, in every period.
This is the node-level Kirchhoff Current Law (KCL) of the conservation-circuit
framing (project plan §1.1).

Re-arranged for the linear system:

.. math::

    \\sum_{j,k} x_{ij}^k  -  \\sum_{j,k} x_{ji}^k  =  E_i - N_i

``DIRECT_MEASURED`` arcs are folded into the right-hand side as known constants;
all other arcs remain as variables in ``matrix_row``.

One constraint row is compiled per *(node, period)* for consumption by
``claimweb.reconstruct.solver``.

Public interface
----------------
``ArcKey``
    Hashable identifier for one arc variable.
``LinearConstraint``
    One row of the sparse linear system.
``ConstraintSet``
    Collection of ``LinearConstraint``\\s plus the referenced unknowns.
``NodeBalance``
    Per-node balance-sheet aggregates (equity, non-financial assets).
``NetworkState``
    Arc facts and node balances for a single period.
``KCLViolation``
    One detected balance-sheet identity violation with full diagnostic.
``KCLResult``
    Aggregate result of :func:`check_kcl`.
``build_kcl_rows``
    Compile one :class:`LinearConstraint` per node.
``check_kcl``
    Directly verify Law 1 on a concrete :class:`NetworkState`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from claimweb.fetchers.base import ArcFact, DataQualityFlag, Period

# ---------------------------------------------------------------------------
# Shared constraint types
# (imported by compile.py and other constraint modules once implemented)
# ---------------------------------------------------------------------------

#: Hashable identifier for one arc variable:
#: (source_node_id, target_node_id, instrument_class_value, period_str)
ArcKey = tuple[str, str, str, str]

_ONE = Decimal("1")
_ZERO = Decimal("0")


@dataclass
class LinearConstraint:
    """One row of the sparse linear system encoding a conservation-law constraint.

    Coefficient convention::

        LHS = sum(coeff * x[arc_key] for arc_key, coeff in matrix_row.items())
        LHS == rhs   (kind="eq")
        LHS <= rhs   (kind="leq")
        LHS >= rhs   (kind="geq")

    All coefficients and ``rhs`` are ``Decimal`` — never ``float``.
    """

    matrix_row: dict[ArcKey, Decimal]  # coefficients keyed by arc variable
    rhs: Decimal                        # right-hand side constant
    kind: Literal["eq", "leq", "geq"]  # constraint type
    provenance: str                     # e.g. "Law 1 (KCL) for node 'X', period 2024-Q4"


@dataclass
class ConstraintSet:
    """Constraints produced by one conservation law for one period."""

    constraints: list[LinearConstraint]
    unknowns: list[ArcKey]  # all arc variables referenced by these constraints


# ---------------------------------------------------------------------------
# KCL-specific types
# ---------------------------------------------------------------------------


@dataclass
class NodeBalance:
    """Per-node balance-sheet aggregates required to enforce Law 1."""

    node_id: str
    period: Period
    equity_millions: Decimal               # E_i
    nonfinancial_assets_millions: Decimal  # N_i (real estate, PP&E, etc.)


@dataclass
class NetworkState:
    """Arc facts and node balance-sheet aggregates for a single period.

    Constraint: every :class:`~claimweb.fetchers.base.ArcFact` in ``arcs``
    must carry ``period == self.period``.  Duplicate arcs sharing the same
    *(source, target, instrument_class, period)* key are treated as additive —
    their amounts are summed before any constraint is applied.
    """

    period: Period
    arcs: list[ArcFact]
    node_balances: dict[str, NodeBalance]  # keyed by node_id

    def __post_init__(self) -> None:
        for arc in self.arcs:
            if arc.period != self.period:
                raise ValueError(
                    f"ArcFact period {arc.period!r} does not match "
                    f"NetworkState period {self.period!r}"
                )

    def arc_value(self, key: ArcKey) -> Decimal:
        """Return the aggregate dollar amount for an :class:`ArcKey`.

        Sums over all :class:`~claimweb.fetchers.base.ArcFact`\\s that share
        the same *(source, target, instrument_class)* triple.  Returns
        ``Decimal("0")`` when no matching arc is found.
        """
        src, tgt, cls_val, _ = key
        total = _ZERO
        for arc in self.arcs:
            if (
                arc.source_node_id == src
                and arc.target_node_id == tgt
                and arc.instrument_class.value == cls_val
            ):
                total += arc.dollar_amount_millions
        return total


@dataclass
class KCLViolation:
    """One node that violates the balance-sheet identity (Law 1)."""

    node_id: str
    period: Period
    residual: Decimal   # asset_sum + N_i - liab_sum - E_i; should be 0
    asset_sum: Decimal  # financial + non-financial assets
    liab_sum: Decimal   # total financial liabilities
    equity: Decimal     # E_i from NodeBalance (or 0 if absent)
    nonfinancial: Decimal  # N_i from NodeBalance (or 0 if absent)
    provenance: str


@dataclass
class KCLResult:
    """Aggregate result of :func:`check_kcl` on a :class:`NetworkState`."""

    period: Period
    satisfied: bool          # True iff no violations detected
    violations: list[KCLViolation]
    node_count: int          # total distinct nodes in the network
    checked_count: int       # nodes examined (may differ from node_count in future)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

# Default relative tolerance: 0.01% of total assets (conservation-laws rule).
_DEFAULT_TOL_REL = Decimal("0.0001")

# Floor on the absolute violation threshold to avoid spurious failures on
# very small test networks (e.g., a two-node network with $1 M total assets
# has a floor of $0.01 M = $10 000, which is still meaningful).
_MIN_ABS_TOL = Decimal("0.01")

# Regex to extract the node ID from a provenance string like:
# "Law 1 (KCL) for node 'X', period 2024-Q4"
_PROV_RE = re.compile(r"Law 1 \(KCL\) for node '([^']+)', period")


def _provenance_node(provenance: str) -> str | None:
    """Extract the node_id embedded in a KCL provenance string."""
    m = _PROV_RE.search(provenance)
    return m.group(1) if m else None


def _group_arcs_by_key_with_flag(
    arcs: list[ArcFact],
    period: Period,
) -> dict[ArcKey, tuple[Decimal, DataQualityFlag]]:
    """Aggregate arcs by *(source, target, instrument, period)* key.

    When duplicate arcs exist for the same key their amounts are summed.
    The highest-quality (lowest ``priority``) ``DataQualityFlag`` is
    retained; the reasoning is that a ``DIRECT_MEASURED`` disclosure always
    wins over a ``PROXY`` measurement of the same arc.
    """
    result: dict[ArcKey, tuple[Decimal, DataQualityFlag]] = {}
    for arc in arcs:
        if arc.period != period:
            continue
        key: ArcKey = (
            arc.source_node_id,
            arc.target_node_id,
            arc.instrument_class.value,
            str(arc.period),
        )
        if key in result:
            amt, flag = result[key]
            best_flag = (
                arc.data_quality_flag
                if arc.data_quality_flag.priority < flag.priority
                else flag
            )
            result[key] = (amt + arc.dollar_amount_millions, best_flag)
        else:
            result[key] = (arc.dollar_amount_millions, arc.data_quality_flag)
    return result


def _group_arcs_by_key(arcs: list[ArcFact], period: Period) -> dict[ArcKey, Decimal]:
    """Aggregate arc amounts by key; discard quality flags."""
    return {k: amt for k, (amt, _) in _group_arcs_by_key_with_flag(arcs, period).items()}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_kcl_rows(network: NetworkState) -> ConstraintSet:
    """Compile one :class:`LinearConstraint` per node enforcing Law 1.

    For each node *i* in the network the generated equality is:

    .. math::

        \\sum_{\\text{unknown outgoing}} x - \\sum_{\\text{unknown incoming}} x
        = E_i - N_i
          - \\sum_{\\text{direct outgoing}} x
          + \\sum_{\\text{direct incoming}} x

    ``DIRECT_MEASURED`` arcs are folded into the RHS as constants; all other
    arcs remain as variables in :attr:`LinearConstraint.matrix_row`.

    Parameters
    ----------
    network:
        Arc facts and node balances for the period to constrain.

    Returns
    -------
    ConstraintSet
        One :class:`LinearConstraint` per node (sorted by node_id) plus
        the list of all unknown :class:`ArcKey`\\s referenced.
    """
    period = network.period
    period_str = str(period)

    arc_data = _group_arcs_by_key_with_flag(network.arcs, period)

    # Collect all nodes mentioned anywhere in the network.
    nodes: set[str] = set(network.node_balances.keys())
    for src, tgt, _, _ in arc_data:
        nodes.add(src)
        nodes.add(tgt)

    constraints: list[LinearConstraint] = []
    all_unknowns: set[ArcKey] = set()

    for node_id in sorted(nodes):
        balance = network.node_balances.get(node_id)
        equity = balance.equity_millions if balance is not None else _ZERO
        nonfinancial = (
            balance.nonfinancial_assets_millions if balance is not None else _ZERO
        )

        # RHS starts as E_i - N_i; measured arcs are absorbed here.
        rhs = equity - nonfinancial
        matrix_row: dict[ArcKey, Decimal] = {}

        for key, (amount, flag) in arc_data.items():
            src, tgt, _, _ = key
            is_out = src == node_id
            is_in = tgt == node_id

            if not (is_out or is_in):
                continue

            if flag == DataQualityFlag.DIRECT_MEASURED:
                # Known constant → fold into RHS.
                # Outgoing arc is an asset (+); its known value reduces the
                # unknown portion, so rhs -= amount.
                # Incoming arc is a liability (−); its known value reduces the
                # unknown portion, so rhs += amount.
                if is_out:
                    rhs -= amount
                if is_in:
                    rhs += amount
            else:
                # Unknown variable → add ±1 coefficient to matrix_row.
                if is_out:
                    matrix_row[key] = matrix_row.get(key, _ZERO) + _ONE
                    all_unknowns.add(key)
                if is_in:
                    matrix_row[key] = matrix_row.get(key, _ZERO) - _ONE
                    all_unknowns.add(key)

        # Drop any arcs whose net coefficient is zero (self-loops or
        # cancellations from duplicate arcs with mixed flags).
        matrix_row = {k: v for k, v in matrix_row.items() if v != _ZERO}

        constraints.append(
            LinearConstraint(
                matrix_row=matrix_row,
                rhs=rhs,
                kind="eq",
                provenance=f"Law 1 (KCL) for node {node_id!r}, period {period_str}",
            )
        )

    return ConstraintSet(
        constraints=constraints,
        unknowns=sorted(all_unknowns),
    )


def check_kcl(
    network: NetworkState,
    *,
    tol: Decimal = _DEFAULT_TOL_REL,
) -> KCLResult:
    """Verify that Law 1 holds at every node in a solved (concrete) network.

    For each node *i*, the residual is:

    .. math::

        r_i = (\\text{asset\\_sum}_i + N_i) - (\\text{liab\\_sum}_i + E_i)

    where ``asset_sum`` is the sum of all outgoing arc amounts and ``liab_sum``
    is the sum of all incoming arc amounts.  A node is flagged as a violation
    when:

    .. math::

        |r_i| > \\max(\\text{tol} \\times \\text{asset\\_sum}_i,\\; 0.01)

    The 0.01 floor prevents spurious violations on very small networks.

    Parameters
    ----------
    network:
        Concrete, solved network whose arc values are all populated.
    tol:
        Relative tolerance as a fraction of total assets at each node.
        Default ``0.0001`` (0.01 %) per the project conservation-laws rule.

    Returns
    -------
    KCLResult
        Summary of which nodes (if any) violate Law 1.
    """
    period = network.period
    period_str = str(period)

    arc_amounts = _group_arcs_by_key(network.arcs, period)

    nodes: set[str] = set(network.node_balances.keys())
    for src, tgt, _, _ in arc_amounts:
        nodes.add(src)
        nodes.add(tgt)

    violations: list[KCLViolation] = []
    checked = 0

    for node_id in sorted(nodes):
        balance = network.node_balances.get(node_id)
        equity = balance.equity_millions if balance is not None else _ZERO
        nonfinancial = (
            balance.nonfinancial_assets_millions if balance is not None else _ZERO
        )

        asset_sum = nonfinancial
        liab_sum = _ZERO

        for (src, tgt, _, _), amount in arc_amounts.items():
            if src == node_id:
                asset_sum += amount
            if tgt == node_id:
                liab_sum += amount

        # Residual: should be 0 when Law 1 is satisfied.
        residual = asset_sum - liab_sum - equity

        threshold = max(tol * asset_sum, _MIN_ABS_TOL)

        if abs(residual) > threshold:
            violations.append(
                KCLViolation(
                    node_id=node_id,
                    period=period,
                    residual=residual,
                    asset_sum=asset_sum,
                    liab_sum=liab_sum,
                    equity=equity,
                    nonfinancial=nonfinancial,
                    provenance=(
                        f"Law 1 (KCL) for node {node_id!r}, period {period_str}: "
                        f"assets={asset_sum}, liabilities={liab_sum}, "
                        f"equity={equity}, residual={residual}"
                    ),
                )
            )

        checked += 1

    return KCLResult(
        period=period,
        satisfied=len(violations) == 0,
        violations=violations,
        node_count=len(nodes),
        checked_count=checked,
    )
