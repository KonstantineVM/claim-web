"""Law 2 — Double-entry consistency per instrument (project plan §1.1).

For every instrument :math:`k` and period :math:`t`, total holdings equal
total issuances when the network boundary is closed. When the boundary is
open (some parties outside :math:`V`), the residual is a boundary term
that is explicitly tracked rather than absorbed silently.

.. math::

    \\sum_{i,j \\in V} x_{ij}^{k}(t)
    = \\text{total holdings of } k \\text{ by parties in } V
    = \\text{total issuances of } k \\text{ by parties in } V + b_k(t)

Planned public interface
------------------------
- ``build_double_entry_rows(facts, *, period) -> ConstraintBlock``
- ``check_double_entry(network, *, tol) -> DoubleEntryResult``
"""
