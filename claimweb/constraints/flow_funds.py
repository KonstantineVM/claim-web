"""Law 4 — Flow-of-funds transactions-vs-positions identity (project plan §1.1).

Change in arc weight between adjacent periods equals net transactions
plus revaluation:

.. math::

    x_{ij}^{k}(t+1) - x_{ij}^{k}(t)
    = F_{ij}^{k}(t \\to t+1) + R_{ij}^{k}(t \\to t+1)

The Z.1 publishes both stock (``L.*`` tables) and flow (``F.*`` tables)
consistently, supplying two independent constraints per period.

Planned public interface
------------------------
- ``build_flow_funds_rows(facts, *, period_from, period_to) -> ConstraintBlock``
- ``check_flow_funds(network_pair, *, tol) -> FlowFundsResult``
"""
