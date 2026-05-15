"""Cascade simulation — Eisenberg-Noe and extensions (project plan §15, §16).

Layered modules; the ``cascade-author`` skill encodes the ordering
discipline (clearing first, then fire-sale, then multi-constraint, then
contingent payments; DebtRank runs in parallel as a centrality overlay,
not in the cascade-application chain).

Modules
-------
- ``eisenberg_noe``     Eisenberg-Noe (2001) clearing-vector backbone
- ``fire_sale``         Cifuentes-Ferrucci-Shin / Cont-Schaanning indirect
                        contagion via fire-sale price impact
- ``multi_constraint``  Coen-Lepore-Schaanning multi-regime binding
                        constraints (capital, liquidity, leverage)
- ``contingent``        Banerjee-Feinstein contingent payments (CDS, certain
                        reinsurance contracts)
- ``debtrank``          Battiston DebtRank centrality overlay
"""
