"""Claim-multiplier computation (project plan §14).

The claim multiplier — one of the two headline outputs of the project —
is the ratio of total financial claims to underlying real assets.
Computed system-wide, per ownership cluster, and per instrument class.
Quarterly series from 2000-Q1 through current.

Planned modules
---------------
- ``system``      system-wide multiplier
- ``cluster``     per ownership-cluster multiplier
- ``instrument``  per instrument-class multiplier
- ``timeseries``  stitches the quarterly series with provenance
"""
