"""Law 3 — Z.1 sectoral aggregate constraints (project plan §1.1).

The Federal Reserve Z.1 release publishes, for every sector :math:`s` and
instrument :math:`k`, the total holdings and total issuances by parties
in :math:`s`. These act as upper-level Kirchhoff equations on the
aggregated sectoral nodes.

.. math::

    \\sum_{i \\in s, j \\in V} x_{ij}^{k}(t) &= Z^{\\text{asset}}_{s,k}(t) \\\\
    \\sum_{j \\in s, i \\in V} x_{ij}^{k}(t) &= Z^{\\text{liab}}_{s,k}(t)

Source tables (per project plan §10.1): L.116 (life insurers), L.121
(P&C), L.207–L.211 (banks, MMFs, ABS issuers), L.226–L.227 (repo, sec
lending).

Planned public interface
------------------------
- ``build_sectoral_rows(z1_loader, *, period) -> ConstraintBlock``
- ``check_sectoral(network, z1_loader, *, tol) -> SectoralResult``
"""
