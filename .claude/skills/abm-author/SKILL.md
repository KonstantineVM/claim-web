---
name: abm-author
description: Author or modify the agent-based modeling layer under claimweb/abm/. Use when implementing agent classes, decision rules, simulator event loops, or calibration routines for the parallel ABM that complements the clearing-vector analytical model. Triggers on phrases like "agent-based model", "ABM", "Bookstaber-Paddrik-Tivnan", "Mesa framework", "agent decision rule", "intra-period sequencing", "trajectory simulation", "agentic crisis". Encodes the ABM-analytical integration discipline from project plan Part XII.
---

# Authoring the ABM layer

The agent-based model is a *complement* to the clearing-vector analytical model (project plan Part XII). The clearing vector gives the terminal-equilibrium answer; the ABM gives the trajectory and reveals path-dependence, intra-period sequencing, and endogenous behavior change that the equilibrium model misses.

Reference architecture: Bookstaber-Paddrik-Tivnan (2018), "An Agent-Based Model for Financial Vulnerability," *Journal of Economic Interaction and Coordination* 13(2):433–466. Methodology survey: Bookstaber (2017), *Annual Review of Financial Economics* 9:85–100.

## File organization

`claimweb/abm/` contains:

- `agents/` — one module per agent class
  - `saver.py` — `SaverAgent` (M1, M2)
  - `bank_treasury.py` — `BankTreasuryAgent` (M3, I4)
  - `mmf.py` — `MMFAgent` (I1)
  - `spv.py` — `SPVAgent` (I2)
  - `fhlb.py` — `FHLBAgent` (I3)
  - `dealer.py` — `DealerAgent` (I4)
  - `custodian.py` — `CustodianAgent` (I5)
  - `aam.py` — `AAMAgent` (I6, I7)
  - `bdc.py` — `BDCAgent` (I8)
  - `insurer.py` — `InsurerAgent` (T1)
  - `reinsurer.py` — `ReinsurerAgent` (T2)
  - `borrower.py` — `BorrowerAgent` (T3)
- `simulator.py` — event loop and state management
- `scenarios.py` — pre-defined crisis scenarios (validation episodes 1/2/3 plus prospective scenarios)
- `calibration.py` — parameter fitting from historical data
- `visualizer.py` — trajectory visualization (animated)
- `validate.py` — ABM-vs-clearing-vector comparison

## Mesa framework

CLAIM-WEB uses the Mesa Python framework for agent management. Mesa is mature and designed exactly for this purpose. The dependency lives in `pyproject.toml`.

Each agent class inherits from `mesa.Agent`. The simulator (`simulator.py`) inherits from `mesa.Model`. Scheduler is configurable per scenario; default is staggered (agents act in priority order based on the event being processed) rather than simultaneous, because financial-network events have meaningful ordering.

## Agent interface

Every agent class implements:

```python
from mesa import Agent
from claimweb.abm.state import AgentState
from claimweb.abm.events import Event, Action

class InsurerAgent(Agent):
    """Life insurer agent.

    State: balance sheet, regulatory ratios (RBC, AAT), hedging program status.
    Decision rule: liquidity management, surrender response, hedging adjustments.
    Reference: project plan §3.3 (T1 nodes), §39, Sen (2023) for VA hedging.
    """

    def __init__(self, unique_id: str, model, initial_state: AgentState):
        super().__init__(unique_id, model)
        self.state = initial_state

    def observe(self, events: list[Event]) -> None:
        """Update agent's view of the world from new events.
        Pure observation — does not change own state beyond perception."""

    def decide(self) -> list[Action]:
        """Given current state and observed events, propose actions for this period.
        Pure function — does not execute the actions."""

    def execute(self, accepted_actions: list[Action]) -> None:
        """Apply the accepted subset of proposed actions to own state.
        The simulator's market-clearing step decides which proposed actions
        are accepted (e.g., counter-party must accept the trade)."""
```

The split between `decide` and `execute` is essential: every agent proposes actions in parallel; the simulator's market-clearing step reconciles conflicts; only then do agents update state.

## Decision rules — parameterization from literature

Each agent class's decision rules come from cited literature. The cited source must be in `docs/LITERATURE.md`:

- **LCR-targeting / leverage-targeting**: Greenwood, Landier, Thesmar (2015), JFE 115(3):471–485.
- **MMF investor redemption response**: Schmidt, Timmermann, Wermers (2016), AER 106(9):2625–2657; post-2014 reform behavior from Cipriani-La Spada-Mulder (2023), JFE 148(2):196–217.
- **Dealer haircut-setting / margin spiral**: Brunnermeier, Pedersen (2009), RFS 22(6):2201–2238.
- **VA hedging program response**: Sen (2023), RFS 36(6):2535–2582.
- **Insurer surrender experience**: actuarial lapse studies from SOA experience tables and insurer 10-K disclosure of policyholder behavior assumptions.
- **Endogenous network formation**: Liu, Paddrik, Yang, Zhang (2020), JBF 112.

Decision rules are *not* invented; they come from peer-reviewed empirical or theoretical papers. Each rule's docstring cites the source.

## Simulator event loop

```python
def simulate(model: ClaimWebABM, scenario: Scenario, horizon: int) -> Trajectory:
    """Run the ABM for `horizon` periods (days or weeks depending on scenario)."""
    trajectory = Trajectory()
    for t in range(horizon):
        # Step 1: exogenous shocks for this period
        exogenous_events = scenario.events_for_period(t)
        model.inject_events(exogenous_events)

        # Step 2: agents observe
        for agent in model.schedule.agents:
            agent.observe(model.recent_events)

        # Step 3: agents decide (parallel, pure)
        proposals = {agent.unique_id: agent.decide() for agent in model.schedule.agents}

        # Step 4: market clearing
        accepted = model.market_clear(proposals)

        # Step 5: agents execute
        for agent in model.schedule.agents:
            agent.execute(accepted.get(agent.unique_id, []))

        # Step 6: conservation check
        model.assert_conservation()  # raises if Laws 1–4 violated

        # Step 7: record state
        trajectory.append(t, model.snapshot())

    return trajectory
```

The market-clearing step (`model.market_clear`) is where conflicts are resolved. Two agents trying to sell the same security to the same buyer at the same time — the simulator resolves by priority rule (e.g., LIFO, FIFO, proportional). The priority rule is part of the scenario configuration.

## Conservation laws in ABM context

Every ABM trajectory must respect the conservation laws at every period. If the simulator's clearing step produces a state that violates Laws 1–4, that is a bug, not a feature. The `model.assert_conservation()` step is mandatory.

The check is the same conservation checker used by the analytical model (`claimweb.constraints`). The ABM doesn't get a relaxed version.

## ABM-analytical integration

For every scenario, both the analytical clearing vector and the ABM trajectory are computed. Three comparison patterns (per project plan §40):

- **Convergent**: ABM trajectory ends at the clearing-vector equilibrium. Confirms the clearing-vector framework is sufficient. Report agreement.
- **Path-dependent**: ABM ends at a different equilibrium depending on intra-period ordering. Report both equilibria as the bracket; clearing-vector understates uncertainty.
- **Non-convergent**: ABM doesn't converge in the simulation horizon. Report this — it indicates the system is in an unstable region.

The `validate.py` module implements this comparison and produces a report per scenario.

## Validation: trajectory-fit for the three historical episodes

The ABM must reproduce not just terminal-state but trajectory for the three episodes (project plan §42):

- **2007 XFABS**: time profile — slow start in July, acceleration in August, peak in September
- **2008 AIG**: trigger sequence — collateral-call escalation, ratings actions, federal intervention
- **2020 COVID**: event ordering — initial credit stress, dealer pullback, MMF redemptions, FHLB surge, Fed intervention

Validation tests live alongside the analytical validation tests in `tests/validation/`. The shape:

```python
@pytest.mark.validation
@pytest.mark.abm
def test_episode_3_2020_trajectory_fit():
    """Verify ABM reproduces the March 2020 event ordering."""
    pre_state = load_solved_network("2020-Q1")
    scenario = COVID_2020_SCENARIO

    trajectory = simulate(model_from(pre_state), scenario, horizon=90)

    # Verify event ordering
    events = trajectory.events_by_type()
    assert events["dealer_repo_pullback"][0].date < events["mmf_redemption_peak"][0].date
    assert events["mmf_redemption_peak"][0].date < events["fhlb_advance_surge"][0].date
    # ... etc
```

## What not to do

- Do not invent decision rules. Every rule cites the literature.
- Do not skip the conservation check. Hooks can't see ABM state directly, so the check has to be in the simulator.
- Do not use Mesa's `RandomActivation` scheduler for our scenarios. Use `BaseScheduler` or a custom staggered scheduler; financial-network event ordering matters.
- Do not exceed ~30s wall-clock for a 90-day daily simulation with ~100 agents. If it's slower than that, profile — usually a numpy/pandas operation is happening per-agent that should be vectorized.
- Do not bypass the analytical layer. The ABM is a complement, not a substitute. Both run; both inform.
