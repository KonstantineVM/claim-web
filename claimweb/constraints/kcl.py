"""Law 1 — Balance-sheet identity at each node (project plan §1.1).

For every node :math:`i` and every period :math:`t`:

.. math::

    \\sum_{j,k} x_{ij}^{k}(t) + N_i(t) = \\sum_{j,k} x_{ji}^{k}(t) + E_i(t)

i.e. total assets equal total liabilities plus equity at every node, in
every period. The node-level Kirchhoff Current Law of the
conservation-circuit framing.

This module compiles one constraint row per ``(node, period)`` into the
sparse linear system consumed by ``claimweb.reconstruct.solver``.

Planned public interface
------------------------
- ``build_kcl_rows(facts, *, period) -> ConstraintBlock``
- ``check_kcl(network, *, tol) -> KCLResult``

Property-based tests (hypothesis) verify the four ``constraint-author``
properties: soundness, completeness, stability, and independence.
"""
