---
description: Conservation-law invariants for any code under claimweb/constraints/, claimweb/reconstruct/, or claimweb/cascade/.
paths:
  - claimweb/constraints/**
  - claimweb/reconstruct/**
  - claimweb/cascade/**
  - scripts/check_conservation.py
---

# Conservation-law invariants

These rules govern any code that touches the network's conservation structure.

## The four laws (from project plan §1.1)

**Law 1 — Balance sheet identity.** At every node `i` in every period `t`:
$$\sum \text{assets at } i = \sum \text{liabilities at } i + \text{equity}_i$$
Total assets equal total liabilities plus equity. *Always.*

**Law 2 — Double-entry consistency.** For every instrument `k` in every period `t`:
$$\sum_{\text{holders in network}} x_k = \sum_{\text{issuers in network}} x_k + \text{boundary}_k$$
A claim that's an asset to one party is a liability to another. The total held in the network must equal the total issued in the network (plus the boundary term capturing parties outside our model).

**Law 3 — Sectoral aggregates.** For every (sector, instrument, period) where Z.1 publishes:
$$\sum_{i \in \text{sector}} \sum_j x_{ij}^k = Z_{s,k}^{\text{asset}}(t)$$
Z.1 sectoral aggregates are the network's *boundary conditions*. The aggregated network must match Z.1 totals exactly within Z.1's published precision (typically one decimal place in billions).

**Law 4 — Flow-of-funds.** For every arc across periods:
$$x_{ij}^k(t+1) - x_{ij}^k(t) = F_{ij}^k + R_{ij}^k$$
Change in position equals net transactions plus revaluation. The Z.1 publishes both F.tables (flows) and L.tables (levels) for cross-checking.

## Implementation invariants

1. **Use `Decimal`, not `float`, for all conservation-related arithmetic.** Floating-point error accumulates and breaks conservation by tiny amounts that compound across the network.

2. **Tolerance levels are strict.** Acceptable residuals:
   - Within a single entity balance sheet: ≤ 0.01% of total assets (typical accounting precision)
   - Within a single instrument's double-entry check: ≤ 0.5% of the total (allows for boundary effects)
   - Within Z.1 aggregation: ≤ Z.1's published precision (usually one decimal place in billions)

3. **Violations are bugs, not features.** A constraint violation in solver output is *never* "close enough." Either:
   - The constraint matrix is incomplete (a law isn't being encoded) — fix the constraint compiler.
   - The input data is internally inconsistent — surface to the user as a data-quality issue.
   - The solver has a bug — fix the solver.

4. **Never silently relax a constraint.** If the solver returns infeasible, that signal is information. Spawn the `network-solver-debugger` subagent before doing anything else.

5. **Test conservation as property-based invariants.** Use hypothesis. The properties:
   - "Apply any law's build_constraints to any synthetic network satisfying the law → all constraints satisfied."
   - "Apply the full constraint compiler to any solved network → it satisfies all four laws."
   - "Apply the cascade simulator to any solved network → before-shock vs after-shock state still satisfies conservation (with the shock's value moved to the appropriate place)."

## When in doubt

The user has stated (project plan, repeated): *"Money does not dissipate."* If your implementation seems to require dissipation to work, it's wrong; find what's missing.

A well-formed cascade *redistributes* claims across nodes (some claims default, some recovery rates are applied, some assets are liquidated and absorbed by other holders). It never makes claims disappear from the system. The total volume of claims plus realized losses across the system equals the pre-cascade total.
