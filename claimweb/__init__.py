"""CLAIM-WEB — U.S. life-insurance regulatory-arbitrage network as a conservation circuit.

This package implements the methodology specified in
``docs/CLAIM_WEB_PROJECT_PLAN.md``. The layout follows project plan §18.

Subsystems
----------
- ``fetchers``    primary-source data acquisition (§10, §11)
- ``normalize``   arc-fact schema normalization (§11)
- ``constraints`` conservation-law compilation (§1.1, §13 Phase B)
- ``reconstruct`` maximum-entropy + minimum-density solvers (§13 Phase C)
- ``cascade``     Eisenberg-Noe clearing with fire-sale, multi-constraint,
                  contingent-payment, and DebtRank extensions (§15, §16)
- ``multiplier``  claim-multiplier computation (§14)
- ``validation``  historical retrodiction — deployment gate (§17)
- ``visualize``   Sankey, node-link, cascade-DAG, time-series renderers
                  (Part VII)
- ``api``         query / drill-down endpoints (Part VIII)
- ``abm``         agent-based parallel simulator (Part XII)

The two headline outputs the package produces are the **claim multiplier**
and the **breaking-point threshold**; see project plan preamble.
"""

__version__ = "0.0.0"
