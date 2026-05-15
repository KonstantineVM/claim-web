---
name: reconstruction-author
description: Author or modify the network reconstruction solvers under claimweb/reconstruct/. Use when implementing maximum-entropy (Upper 2004), minimum-density (Anand-Craig-von Peter 2015), or the harness that brackets the two. Triggers on phrases like "maximum entropy solver", "minimum density", "RAS algorithm", "iterative proportional fitting", "reconstruct the network", "fill in the blanks". Encodes how both methods integrate with the constraint system.
---

# Authoring a reconstruction solver

CLAIM-WEB runs *both* maximum-entropy and minimum-density network reconstruction and reports the bracket. This is non-negotiable (project plan conclusion / no-compromise commitment). The two methods bracket the true network — ME underestimates contagion, MD overestimates (Anand-Craig-von Peter 2015 result; Mistrulli 2011 empirical demonstration on Bank of Italy data).

## File organization

`claimweb/reconstruct/` contains:

- `max_entropy.py` — Upper 2004 / Anand-Craig-von Peter ME formulation
- `min_density.py` — Anand-Craig-von Peter MD formulation
- `solver.py` — The harness that runs both and produces the bracket
- `validate.py` — Internal consistency checks on solver outputs

## Mandatory pre-implementation step

Before writing or modifying any solver, spawn the `literature-checker` subagent with the relevant paper. The solver implementations must match the published algorithm; deviations require user authorization.

## Maximum entropy

Reference: Upper (2004), "Estimating bilateral exposures in the German interbank market", *European Economic Review* 48:827–849. Survey: Upper (2011), *Journal of Financial Stability* 7:111–125.

The ME formulation:
$$\hat{X}^{ME} = \arg\max_X \; \left( -\sum_{ij,k} x_{ij}^k \log x_{ij}^k \right) \quad \text{s.t.} \; C \cdot \text{vec}(X) = b, \; X \geq 0$$

Standard implementation via iterative proportional fitting (RAS algorithm). Algorithm:

```
initialize X(0) = matrix of ones (or any positive matrix)
repeat:
    scale rows: X(t+1)_ij = X(t)_ij * (target_row_i / current_row_i)
    scale cols: X(t+2)_ij = X(t+1)_ij * (target_col_j / current_col_j)
until convergence (max abs change < tolerance)
```

Convergence properties:
- Converges if and only if the marginals are consistent (row sums = col sums of the true network).
- If they are not consistent, the iteration oscillates; detect and report.
- Tolerance: 1e-8 in dollar-million units typically achieves Decimal-precision agreement.

Verification: an LP-based alternative (cvxpy with the entropy objective) should produce the same answer up to convergence tolerance. Run both on small problems to confirm equivalence.

## Minimum density

Reference: Anand, Craig & von Peter (2015), "Filling in the Blanks: Network Structure and Interbank Contagion", *Quantitative Finance* 15(4):625–636.

The MD formulation: among all feasible network matrices, select the one with the minimum number of non-zero entries (sparsest). Combinatorial; the paper's algorithm is a relaxation method:

```
initialize: place all probability mass on the diagonal (or any sparse pattern)
repeat:
    propose a random reallocation: pick (i,j) and (k,l), shift mass
    accept if it strictly decreases density (Hamming weight)
    occasionally accept if it ties (Metropolis-style anti-stuck)
until no improvement for N iterations
```

Implementation notes:
- The exact MD problem is NP-hard; the paper's heuristic is what we implement
- The R package `NetworkRiskMeasures` ships a working version; the project-plan §2.14 cites it. We can study it as a reference and Python-port the algorithm
- The "small probability of link deletion to allow the algorithm to cover the entire space of possible network configurations" (Anand et al. 2014 working paper) is essential for ergodicity; do not omit
- MD is more sensitive to starting state than ME; run multiple random restarts (project plan recommends ≥ 10) and report the best

## The harness (solver.py)

The harness runs both methods, validates the outputs, and produces the bracketed network. Interface:

```python
def solve_network(period: Period, constraints: ConstraintSet) -> SolvedNetwork:
    """Solve the network reconstruction for `period` given `constraints`.
    Returns a SolvedNetwork with ME and MD estimates per arc, plus the bracket."""

@dataclass(frozen=True)
class SolvedNetwork:
    period: Period
    arcs: dict[ArcKey, ArcEstimate]
    methodology_version: str
    solver_metadata: SolverMetadata

@dataclass(frozen=True)
class ArcEstimate:
    me_value: Decimal
    md_value: Decimal
    bracket_min: Decimal               # min(me, md) for unmeasured; equals direct value for measured
    bracket_max: Decimal               # max(me, md)
    data_quality: DataQualityFlag      # how the arc was determined
    direct_measurement: Decimal | None # if applicable
```

The harness must:
1. Verify the constraint system is feasible. If infeasible, surface to the user (don't silently relax).
2. Run ME. If it doesn't converge, report and stop.
3. Run MD with multiple random restarts. Take the best.
4. Compute the bracket per arc.
5. Verify the produced ArcEstimates satisfy all four conservation laws (Laws 1–4) within tolerance. If not, spawn the `network-solver-debugger` subagent.
6. Emit the SolvedNetwork to `data/output/network/{period}/`.

## Testing requirements

- **Property-based tests on synthetic networks of known structure.** Generate small (4–10 node) networks with known true X, compute the marginals, give them to the solver, and verify the solver recovers the X (ME on a feasible problem with unique solution must recover exactly).
- **Convergence tests.** Verify ME converges on small problems; verify MD's random restart bound is set high enough.
- **Bracket invariants.** Verify ME ≤ MD does NOT always hold (sometimes ME > MD on a specific arc); verify min(ME, MD) and max(ME, MD) bracket the true value on synthetic problems.
- **Cross-check against R `NetworkRiskMeasures`** on the same input data, to validate the Python port. This requires R installation; mark these tests `@pytest.mark.integration_r` and skip them by default.

## What not to do

- Do not ship ME without MD (or vice versa). The bracket is the project's headline epistemological discipline.
- Do not skip the conservation-law verification step. The solver might satisfy the constraints in the constraint matrix and yet produce a network that fails our conservation checks if the constraint matrix is incomplete.
- Do not silently extend convergence iterations. If a problem doesn't converge, that is a signal; report it.
