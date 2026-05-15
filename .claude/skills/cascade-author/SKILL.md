---
name: cascade-author
description: Author or modify the cascade simulator under claimweb/cascade/. Use when implementing Eisenberg-Noe clearing, Cont-Schaanning fire-sale extension, Coen-Lepore-Schaanning multi-constraint binding, Banerjee-Feinstein contingent payments, or Battiston DebtRank. Triggers on phrases like "Eisenberg-Noe", "clearing vector", "fire sale", "cascade", "DebtRank", "fictitious default", "contagion simulator". Encodes the layering discipline.
---

# Authoring a cascade module

The cascade simulator is the project's analytical engine for the breaking-point output. It is layered: a base clearing-vector model (Eisenberg-Noe 2001) plus a sequence of independent extensions. Implementation discipline preserves the layering so extensions can be enabled/disabled and the contributions of each can be attributed.

## File organization

`claimweb/cascade/` contains:

- `eisenberg_noe.py` — base clearing-vector algorithm (Eisenberg & Noe 2001)
- `fire_sale.py` — Cont-Schaanning indirect contagion via overlapping portfolios
- `multi_constraint.py` — Coen-Lepore-Schaanning multi-regime constraint binding
- `contingent.py` — Banerjee-Feinstein contingent-payment extension for reinsurance and VA arcs
- `debtrank.py` — Battiston et al. distress-propagation centrality
- `simulator.py` — The harness that assembles base + extensions into a single shock-to-cascade pipeline

## Mandatory pre-implementation step

Spawn `literature-checker` against the relevant paper before writing any module here. The cascade math is exact, the cited results are precise, and a small error in the algorithm produces wrong outputs that are hard to spot.

## Layering discipline

Each extension takes the previous layer's output as input and returns a refined output. Like middleware. The shape:

```python
def eisenberg_noe_clearing(
    network: SolvedNetwork,
    capacities: dict[NodeID, Decimal],
    shock: Shock,
) -> ClearingResult:
    """Base clearing-vector algorithm. Computes the fixed-point payment vector."""

def fire_sale_extension(
    base: ClearingResult,
    network: SolvedNetwork,
    asset_liquidity: dict[AssetClass, LiquidityProfile],
    config: FireSaleConfig,
) -> ClearingResult:
    """Iterates fire-sale price moves until joint clearing-vector + price fixed point.
    Returns refined ClearingResult."""

def multi_constraint_extension(
    base: ClearingResult,
    network: SolvedNetwork,
    regime_constraints: dict[NodeID, RegimeConstraintSet],
) -> ClearingResult:
    """Respects each node's binding constraint (CET1 / LCR / RBC / BMA EBS / FHFA capital).
    Returns refined ClearingResult."""

# ... etc
```

The harness composes them in a project-specified order:

```python
def simulate_cascade(network, shock, config) -> CascadeOutput:
    result = eisenberg_noe_clearing(network, config.capacities, shock)
    if config.fire_sale_enabled:
        result = fire_sale_extension(result, network, config.asset_liquidity, config.fire_sale)
    if config.multi_constraint_enabled:
        result = multi_constraint_extension(result, network, config.regime_constraints)
    if config.contingent_enabled:
        result = contingent_extension(result, network, config.contingent_arcs)
    debt_rank = compute_debt_rank(network, result)
    return CascadeOutput(clearing=result, debt_rank=debt_rank, ...)
```

## Per-module specifications

### Eisenberg-Noe (eisenberg_noe.py)

The fixed-point iteration:
$$p_i^{(n+1)} = \min\left(\bar{p}_i, \; c_i - \Delta r_i + \sum_j \pi_{ji} p_j^{(n)}\right)$$

Fictitious-default algorithm (Eisenberg-Noe 2001):
1. Initialize $p^{(0)} = \bar{p}$.
2. Iterate.
3. Identify the set of defaulting nodes at the fixed point.
4. Recompute with the defaulted set known; assert convergence.

Existence and uniqueness conditions (the paper's Theorem 2): the clearing vector is the unique fixed point under "mild regularity conditions". Verify the regularity conditions hold for our network before declaring the output trustworthy.

Output:
```python
@dataclass(frozen=True)
class ClearingResult:
    clearing_vector: dict[NodeID, Decimal]    # p* per node
    defaulting_nodes: set[NodeID]
    shortfalls: dict[NodeID, Decimal]         # max(0, bar_p_i - p*_i)
    iterations: int
    converged: bool
    metadata: dict
```

### Fire-sale extension (fire_sale.py)

Cont-Schaanning (2017) framework. Inverse-demand function for each asset class:
$$\Delta p = -\beta_k \cdot \Delta q / \text{market depth}_k$$

Calibration parameters $\beta_k$ from Duarte-Eisenbach (2021) and Greenwood-Landier-Thesmar (2015). For asset classes not directly covered there, use the project plan §31's mitigation: "report cascade outputs with a range of price-impact parameters" — i.e., produce a sensitivity range.

Joint fixed point:
1. Start with the EN clearing-vector result.
2. Each defaulting node liquidates illiquid assets to meet shortfall.
3. The aggregate liquidation per asset class generates a price change via the inverse demand function.
4. Mark down all holders' portfolios at the new price.
5. Some non-defaulting nodes are now defaulting because their marked-down capital is too thin.
6. Re-run EN with the new capacities and the new asset prices.
7. Iterate to joint fixed point.

### Multi-constraint extension (multi_constraint.py)

Coen-Lepore-Schaanning (2019) BoE Staff Working Paper 793. Each node has a `RegimeConstraintSet` listing the constraints it must satisfy. Per project plan §3.4 (regulator nodes), the relevant regimes are:
- LISCC banks: CET1 ratio, LCR, SLR, NSFR (all the Basel III constraints)
- Insurers: RBC (NAIC formula), AAT (actuarial asset adequacy)
- FHLB: FHFA capital framework
- Offshore reinsurers: BMA Economic Balance Sheet or CIMA prescribed regime

For each defaulting-from-EN node, check which constraint binds. The action set depends on the binding constraint:
- Capital constraint → must raise capital or deleverage (sell assets, triggering fire sale)
- Liquidity constraint → must obtain liquidity (draw FHLB advance, raise wholesale funding, sell HQLA)

The extension produces revised actions that may differ from the EN-only or EN+fire-sale result.

### Contingent extension (contingent.py)

Banerjee-Feinstein (2019). For arcs whose payment depends on the *wealth* of the firms in the network (reinsurance treaties, CDS, variable-annuity hedges), the clearing vector requires the contingent-payment extension. The fixed-point structure is the same as EN but the $\bar{p}_i$ depend on the clearing vector itself (a higher-order fixed point).

For CLAIM-WEB, the contingent arcs are:
- Reinsurance treaties (A6 arc class) — cedent's recoveries depend on offshore reinsurer's solvency
- Variable annuity guarantees (Koijen-Yogo 2022) — insurer's contingent liability depends on equity markets, modeled as a stochastic shock that interacts with the clearing vector

### DebtRank (debtrank.py)

Battiston et al. (2012), *Scientific Reports* 2:541. Feedback-centrality measure for distress propagation. Distinct from EN: DebtRank measures distress propagation *without requiring default*; a node experiencing 30% distress propagates that distress through its liabilities even if it doesn't default.

Algorithm:
1. Initialize distress vector $h^{(0)}$ with the shock at the source nodes.
2. Iterate: each node propagates a fraction $h_i^{(n)}$ of its distress to creditors weighted by the leverage matrix.
3. Sum total propagated distress; that's the source node's DebtRank.

DebtRank is computed *on the solved network* and *given* the EN/fire-sale/multi-constraint cascade result, as an overlay. It identifies systemically important nodes whose distress (not default) has the largest network impact.

## Testing requirements

- **Synthetic test networks where the answer is computable by hand.** A 3-node network, a 5-node ring, a 5-node star — every cascade implementation must reproduce hand-computed clearing vectors on these.
- **Comparison to published reference results.** Eisenberg-Noe (2001) and Acemoglu-Ozdaglar-Tahbaz-Salehi (2015) include worked examples; the implementation must match them exactly to Decimal tolerance.
- **Monotonicity invariants.** Larger shocks → weakly larger cascades; fewer assets liquidated under higher fire-sale liquidity → weakly smaller secondary defaults; etc. Property-based tests.
- **Historical retrodiction.** The 2007 / 2008 / 2020 episodes are the deployment gate. Spawn `retrodiction-replayer` subagent to validate.

## What not to do

- Do not combine the base algorithm and extensions in one module. The layering is the discipline.
- Do not skip the contingent extension for reinsurance arcs. Naive EN treats reinsurance as a fixed liability, which is wrong — recoveries depend on offshore solvency, which depends on the clearing vector.
- Do not commit cascade code without the synthetic-network tests. Even if it "looks right", subtle bugs in iterative algorithms can pass casual review.
