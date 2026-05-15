"""Agent-based parallel simulator (project plan Part XII).

A *complement*, not a substitute, for the Eisenberg-Noe clearing-vector
model. Provides the two things the analytical layer misses:

1. Intra-period sequencing (Bookstaber-Paddrik-Tivnan 2018)
2. Endogenous behavior change under stress
   (Liu-Paddrik-Yang-Zhang 2020)

Built on the Mesa Python framework (project plan §41) plus
financial-network-specific decision rules.

Modules
-------
- ``agents/``      one module per agent class (per §39)
- ``simulator``    event-loop and state management
- ``scenarios``    pre-defined crisis scenarios
- ``calibration``  decision-rule parameter fitting from historical data
"""
