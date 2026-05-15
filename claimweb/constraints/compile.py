"""Aggregate all four conservation laws into a single sparse linear system.

This module is the entry point for :mod:`claimweb.reconstruct.solver`.  It
collects constraint rows from each of the four conservation-law modules and
assembles them into a :class:`CompiledSystem` — an ordered list of
:class:`~claimweb.constraints.kcl.LinearConstraint` rows together with the
ordered list of unknown arc variables (columns).

The four laws (project plan §1.1) and one soft constraint:

* **Law 1 (KCL)** — balance-sheet identity at each node, always applied.
* **Law 2 (double-entry)** — instrument-level holdings equal issuances plus
  boundary; applied only when *boundary_terms* is supplied.
* **Law 3 (sectoral)** — Z.1 sectoral aggregate boundary conditions; applied
  only when *sector_map* and *sectoral_totals* are supplied.
* **Law 4 (flow-of-funds)** — period-to-period position change equals
  transactions plus revaluation; applied only when *network_from* and
  *flow_terms* are supplied.
* **Non-negativity** — arc weights are non-negative; encoded as ``geq``
  constraints; included by default, opt-out via *include_nonnegativity=False*.

Public interface
----------------
``LawStats``
    Per-law summary: constraint count and eq/leq/geq breakdown.
``CompiledSystem``
    The assembled constraint system consumed by ``claimweb.reconstruct.solver``.
``compile_constraints``
    Build the :class:`CompiledSystem` from one or two :class:`NetworkState`
    objects plus optional per-law boundary data.

Usage
-----
Minimal (Laws 1 + non-negativity only)::

    from claimweb.constraints.compile import compile_constraints
    system = compile_constraints(network)

With all four laws::

    system = compile_constraints(
        network,
        boundary_terms=instrument_totals,
        sector_map=sector_map,
        sectoral_totals=sectoral_totals,
        network_from=network_q3,
        flow_terms=flow_terms,
        revaluation_terms=revaluation_terms,
    )

The solver then calls ``system.to_index()`` to obtain column indices and
builds the sparse matrix from ``system.constraints``.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from claimweb.constraints.double_entry import (
    InstrumentTotals,
    build_double_entry_rows,
)
from claimweb.constraints.flow_funds import (
    FlowTerms,
    RevaluationTerms,
    build_flow_funds_rows,
)
from claimweb.constraints.kcl import (
    ArcKey,
    ConstraintSet,
    LinearConstraint,
    NetworkState,
    build_kcl_rows,
)
from claimweb.constraints.sectoral import (
    SectoralTotals,
    SectorMap,
    build_sectoral_rows,
)

_ZERO = Decimal("0")
_ONE = Decimal("1")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class LawStats:
    """Per-law constraint count and type breakdown."""

    name: str   # e.g. "KCL (Law 1)"
    count: int  # total number of constraints from this source
    n_eq: int   # equality constraints
    n_leq: int  # upper-bound inequality constraints
    n_geq: int  # lower-bound inequality constraints


@dataclass
class CompiledSystem:
    """Assembled sparse linear constraint system for the network solver.

    ``constraints`` is the ordered list of row vectors; ``unknowns`` is the
    ordered list of column variables.  Together they define the constraint
    matrix *C* and right-hand side vector *b* such that:

    .. code-block:: text

        C[i][j] = constraints[i].matrix_row.get(unknowns[j], 0)
        b[i]    = constraints[i].rhs

    with equality / inequality kind given by ``constraints[i].kind``.

    All coefficient and rhs values are :class:`~decimal.Decimal`.  The solver
    converts to ``float`` at its boundary; see the decimal-arithmetic rule in
    ``.claude/rules/decimal-arithmetic.md`` for the precision protocol.
    """

    constraints: list[LinearConstraint]
    unknowns: list[ArcKey]
    law_stats: list[LawStats]

    @property
    def n_constraints(self) -> int:
        """Total number of constraint rows."""
        return len(self.constraints)

    @property
    def n_unknowns(self) -> int:
        """Total number of unknown arc variables (columns)."""
        return len(self.unknowns)

    @property
    def n_equality(self) -> int:
        """Number of equality constraints."""
        return sum(1 for c in self.constraints if c.kind == "eq")

    @property
    def n_inequality(self) -> int:
        """Number of inequality constraints (leq + geq)."""
        return sum(1 for c in self.constraints if c.kind in ("leq", "geq"))

    def to_index(self) -> dict[ArcKey, int]:
        """Return a mapping from :class:`ArcKey` to column index.

        Convenience method for the solver when building the dense or sparse
        coefficient matrix.
        """
        return {key: i for i, key in enumerate(self.unknowns)}

    def summary(self) -> str:
        """One-line human-readable summary of the assembled system."""
        return (
            f"CompiledSystem: {self.n_constraints} constraints "
            f"({self.n_equality} eq, {self.n_inequality} ineq) "
            f"× {self.n_unknowns} unknowns; "
            f"laws: {', '.join(s.name + '=' + str(s.count) for s in self.law_stats)}"
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _law_stats(name: str, constraints: list[LinearConstraint]) -> LawStats:
    n_eq = sum(1 for c in constraints if c.kind == "eq")
    n_leq = sum(1 for c in constraints if c.kind == "leq")
    n_geq = sum(1 for c in constraints if c.kind == "geq")
    return LawStats(name=name, count=len(constraints), n_eq=n_eq, n_leq=n_leq, n_geq=n_geq)


def _collect(
    cs: ConstraintSet,
    all_constraints: list[LinearConstraint],
    all_unknowns: set[ArcKey],
) -> None:
    """Append constraints and unknowns from *cs* into the accumulators."""
    all_constraints.extend(cs.constraints)
    all_unknowns.update(cs.unknowns)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_constraints(
    network: NetworkState,
    *,
    # Law 2 — double-entry
    boundary_terms: InstrumentTotals | None = None,
    # Law 3 — sectoral aggregates
    sector_map: SectorMap | None = None,
    sectoral_totals: SectoralTotals | None = None,
    # Law 4 — flow-of-funds (requires a second, earlier network)
    network_from: NetworkState | None = None,
    flow_terms: FlowTerms | None = None,
    revaluation_terms: RevaluationTerms | None = None,
    # Non-negativity (all arc weights ≥ 0)
    include_nonnegativity: bool = True,
) -> CompiledSystem:
    """Aggregate all active conservation laws into one :class:`CompiledSystem`.

    Laws 1 (KCL) is always applied.  Laws 2, 3, and 4 are applied only when
    their respective boundary data are supplied.  Non-negativity constraints
    (``x ≥ 0`` for every unknown arc variable) are included by default.

    Parameters
    ----------
    network:
        Arc facts and node balances for the primary period to constrain.
        Used for Laws 1, 2, 3, and as *period_to* for Law 4.
    boundary_terms:
        Law 2 — mapping from ``ArcClass.value`` string to the expected
        aggregate instrument total in millions USD.  If ``None``, Law 2 rows
        are omitted.
    sector_map:
        Law 3 — mapping from node_id to sector_id string.  Both *sector_map*
        and *sectoral_totals* must be non-``None`` for Law 3 to fire.
    sectoral_totals:
        Law 3 — mapping from *(sector_id, instrument_value, "asset"|"liab")*
        to the Z.1 expected total in millions USD.  If ``None``, Law 3 rows
        are omitted.
    network_from:
        Law 4 — arc facts and node balances for the *preceding* period.  Both
        *network_from* and a non-empty *flow_terms* must be supplied for Law 4
        to fire.
    flow_terms:
        Law 4 — mapping from ``(src, tgt, instrument_value)`` to net
        transactions *F* in millions USD.
    revaluation_terms:
        Law 4 — mapping from ``(src, tgt, instrument_value)`` to revaluation
        *R* in millions USD.  Absent keys default to zero.  May be ``None``.
    include_nonnegativity:
        If ``True`` (default), append one ``geq`` constraint per unknown arc
        variable enforcing ``x ≥ 0``.  Solvers that natively support variable
        bounds may set this to ``False`` and handle bounds separately.

    Returns
    -------
    CompiledSystem
        Ordered constraints, ordered unknowns, and per-law statistics.

    Raises
    ------
    ValueError
        If *network_from* is supplied without *flow_terms* (or vice-versa) the
        Law 4 inputs are inconsistent; no exception is raised — Law 4 is simply
        skipped — but if *network_from.period* equals *network.period* a
        ``ValueError`` is raised because a zero-length transition produces a
        trivially degenerate constraint.
    """
    all_constraints: list[LinearConstraint] = []
    all_unknowns: set[ArcKey] = set()
    stats: list[LawStats] = []

    # ------------------------------------------------------------------
    # Law 1 — Balance-sheet identity (KCL) at each node.  Always applied.
    # ------------------------------------------------------------------
    kcl_cs = build_kcl_rows(network)
    _collect(kcl_cs, all_constraints, all_unknowns)
    stats.append(_law_stats("KCL (Law 1)", kcl_cs.constraints))

    # ------------------------------------------------------------------
    # Law 2 — Double-entry consistency per instrument.
    # Applied only when boundary_terms is non-None.
    # ------------------------------------------------------------------
    if boundary_terms is not None:
        de_cs = build_double_entry_rows(
            network.arcs,
            period=network.period,
            boundary_terms=boundary_terms,
        )
        _collect(de_cs, all_constraints, all_unknowns)
        stats.append(_law_stats("double_entry (Law 2)", de_cs.constraints))

    # ------------------------------------------------------------------
    # Law 3 — Z.1 sectoral aggregate boundary conditions.
    # Applied only when both sector_map and sectoral_totals are non-None.
    # ------------------------------------------------------------------
    if sector_map is not None and sectoral_totals is not None:
        sec_cs = build_sectoral_rows(
            network.arcs,
            period=network.period,
            sector_map=sector_map,
            sectoral_totals=sectoral_totals,
        )
        _collect(sec_cs, all_constraints, all_unknowns)
        stats.append(_law_stats("sectoral (Law 3)", sec_cs.constraints))

    # ------------------------------------------------------------------
    # Law 4 — Flow-of-funds transactions-vs-positions.
    # Applied only when network_from is non-None and flow_terms is non-empty.
    # ------------------------------------------------------------------
    if network_from is not None and flow_terms:
        if network_from.period == network.period:
            raise ValueError(
                f"network_from.period ({network_from.period!r}) must differ "
                f"from network.period ({network.period!r}); a zero-length "
                "transition produces degenerate Law 4 constraints."
            )
        ff_cs = build_flow_funds_rows(
            network_from.arcs,
            network.arcs,
            period_from=network_from.period,
            period_to=network.period,
            flow_terms=flow_terms,
            revaluation_terms=revaluation_terms,
        )
        _collect(ff_cs, all_constraints, all_unknowns)
        stats.append(_law_stats("flow_funds (Law 4)", ff_cs.constraints))

    # ------------------------------------------------------------------
    # Non-negativity: x_ij^k >= 0 for every unknown arc variable.
    # These are lower-bound inequalities consumed by the solver.
    # ------------------------------------------------------------------
    if include_nonnegativity:
        nonneg: list[LinearConstraint] = [
            LinearConstraint(
                matrix_row={key: _ONE},
                rhs=_ZERO,
                kind="geq",
                provenance=f"non-negativity: arc {key}",
            )
            for key in sorted(all_unknowns)
        ]
        all_constraints.extend(nonneg)
        stats.append(_law_stats("non-negativity", nonneg))

    return CompiledSystem(
        constraints=all_constraints,
        unknowns=sorted(all_unknowns),
        law_stats=stats,
    )
