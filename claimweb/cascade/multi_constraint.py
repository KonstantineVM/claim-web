"""Coen-Lepore-Schaanning multi-regime binding-constraint cascade
(project plan §15).

Real institutions face multiple simultaneous regulatory constraints —
capital ratios, leverage ratios, liquidity coverage. Which constraint
binds first determines the institution's response under stress. The
Coen-Lepore-Schaanning framework integrates this multiplicity into the
cascade computation.

Per ``cascade-author`` skill: layered after Eisenberg-Noe and fire-sale,
respecting the ordering discipline.

Planned public interface
------------------------
- ``clear_with_multi_constraint(network, capacities, regulatory_state, *,
                                 max_iter, tol) -> ClearingVectorMultiRegime``
"""
