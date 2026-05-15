"""ABM event loop and state management (project plan §39, §41).

Each simulation period:

1. Apply exogenous shocks (from the scenario)
2. Each agent observes the new state
3. Each agent evaluates its ``decision_rule``
4. Actions execute in priority order; market-clearing resolves conflicts
5. Balance sheets updated; conservation laws enforced (any ABM output
   violating Laws 1–4 is a bug)
6. Next period begins

Configurable horizon: typically 90 days at daily granularity for crisis
scenarios; 4 quarters at weekly granularity for slow-burn scenarios.

Planned public interface
------------------------
- ``Simulator(network, agents, scenario, *, dt, horizon) -> SimulatorRun``
"""
