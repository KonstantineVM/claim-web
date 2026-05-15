---
name: constraint-author
description: Author or modify a conservation-law constraint under claimweb/constraints/. Use whenever implementing or extending the four conservation laws (balance-sheet identity, double-entry consistency, sectoral aggregates, flow-of-funds). Triggers on phrases like "implement KCL check", "add double-entry constraint", "balance sheet identity", "constraint matrix", "Law 1/2/3/4". Encodes how constraints must integrate with the solver.
---

# Authoring a constraint

The four conservation laws (project plan §1.1) are the mathematical spine of CLAIM-WEB. The constraints module compiles them into a form the reconstruction solver can consume. Implementation discipline here is unusually strict because (a) the conservation laws are project invariants and (b) the constraint matrix is the foundation for all downstream computation.

## File organization

`claimweb/constraints/` contains:

- `kcl.py` — Law 1 (balance-sheet identity at each node)
- `double_entry.py` — Law 2 (instrument-level conservation)
- `sectoral.py` — Law 3 (Z.1 sectoral aggregates as boundary conditions)
- `flow_funds.py` — Law 4 (transactions vs positions reconciliation across periods)
- `prior.py` — Soft constraints from prior knowledge (entity-type compatibility, etc.)
- `compile.py` — Aggregates the laws into a single sparse constraint matrix

Each law has the same module shape: a `build_constraints(network: NetworkState) -> ConstraintSet` function that returns linear constraints as (matrix_block, rhs_block, equality_or_inequality).

## The ConstraintSet type

```python
@dataclass
class LinearConstraint:
    matrix_row: dict[ArcKey, Decimal]   # coefficients on each arc unknown
    rhs: Decimal                         # right-hand side
    kind: Literal["eq", "leq", "geq"]   # equality or inequality
    provenance: str                      # human-readable: "Law 1 for node X, period Y"

@dataclass
class ConstraintSet:
    constraints: list[LinearConstraint]
    unknowns: list[ArcKey]               # the variables this set references
```

The compile step takes ConstraintSets from each law and assembles them into a single sparse linear system. The solver consumes the assembled system.

## Per-law specifications

### Law 1 — Balance sheet identity

For every (node, period), generate one equality:
$$\sum_{\text{arcs incident as asset}} x = \sum_{\text{arcs incident as liability}} x + \text{equity}$$

The equity term is observed (from balance-sheet totals); the arcs are the unknowns. If some arcs are directly measured (DIRECT_MEASURED quality), they enter the rhs as constants rather than as variables.

### Law 2 — Double-entry consistency

For every (instrument, period), generate one equality:
$$\sum_{\text{all holders in network}} x_k = \sum_{\text{all issuers in network}} x_k + \text{boundary term}$$

The boundary term captures issuance held by or issuance by parties outside the modeled set (e.g., the long tail of small insurers we don't model entity-by-entity).

### Law 3 — Sectoral aggregates

For every (sector, instrument, period) tuple where Z.1 publishes a value, generate one equality:
$$\sum_{i \in \text{sector}, j} x_{ij}^k = Z_{s,k}^{\text{asset}}(t)$$

and the corresponding row sum for liabilities. The Z.1 publishes both, providing two constraints per (sector, instrument, period).

### Law 4 — Flow-of-funds

For every (arc, period-to-period-transition), generate one equality:
$$x_{ij}^k(t+1) - x_{ij}^k(t) - F_{ij}^k(t \to t+1) - R_{ij}^k(t \to t+1) = 0$$

where F is the transactions term (from Z.1 flow tables) and R is the revaluation term (computed from market-price changes for marked-to-market arcs). For book-value arcs, R = 0.

### Prior — Soft constraints

Entity-type compatibility constraints encoded as bounds on specific arc variables:
- An MMF cannot hold a CLO mezzanine tranche directly → upper bound 0 on that arc
- An FHLB cannot advance to a non-member → upper bound 0
- A funding agreement can only be issued by an insurer, only held by an SPV → upper bound 0 on all other source/target combinations
- ...etc.

Encode each compatibility rule as an upper-bound LinearConstraint with `kind="leq"`.

## Testing discipline (the hardest part)

Conservation-law tests are property-based via hypothesis. The shape:

```python
@given(networks(small_random_network_strategy))
def test_law1_holds_on_built_constraints(network):
    cs = kcl.build_constraints(network)
    # For every node, when we substitute the network's true arc values
    # into the LHS of the law's constraint, we should get the equity value
    # to within Decimal tolerance.
    for c in cs.constraints:
        lhs = sum(coeff * network.arc_value(arc_key) for arc_key, coeff in c.matrix_row.items())
        assert abs(lhs - c.rhs) < Decimal("0.01"), f"Law 1 violation: {c.provenance}"
```

The properties to test for every law:
1. **Soundness.** On a synthetic network satisfying the law by construction, build_constraints emits constraints all of which are satisfied.
2. **Completeness.** On a synthetic network violating the law by construction (one bad arc), at least one constraint in the output is violated.
3. **Stability.** Small perturbations of input data produce small changes in constraint coefficients (no chaotic behavior).
4. **Independence.** Constraints from different laws don't accidentally entangle (the compile step should preserve provenance).

## What not to do

- Do not implement a constraint module without property-based tests. The constraints are the foundation; if they're wrong, everything downstream is wrong.
- Do not use floats for the matrix coefficients. Use Decimal. Conservation laws are sensitive to floating-point error.
- Do not silently relax a constraint when it produces an infeasible system. Surface the infeasibility — it's almost always a data-quality issue, not a constraint-formulation issue. Spawn the `network-solver-debugger` subagent to investigate.
- Do not add a constraint that isn't traceable to a specific law or to a published source. The "prior" constraints in particular must each cite the rule they encode (NAIC SSAP, FHFA regulation, Rule 2a-7 paragraph, etc.).
