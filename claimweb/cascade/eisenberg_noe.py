"""Eisenberg-Noe (2001) clearing-vector algorithm (project plan §15).

The clearing payment vector :math:`p^*` is the largest fixed point of

.. math::

    p_i^{*} = \\min\\!\\left(\\bar{p}_i,\\;
              c_i + \\sum_j \\pi_{ji}\\, p_j^{*}\\right)

where :math:`\\bar{p}_i` is total liabilities at node :math:`i`,
:math:`c_i` is real-dollar capacity (cash and cash-equivalent holdings),
and :math:`\\pi_{ji}` is the relative claim of :math:`i` on :math:`j`.
Solved by the fictitious-default algorithm in polynomial time.

Per project plan §15, the breaking-point output is:

.. math::

    \\theta^{*} = \\inf \\{\\theta > 0 : \\exists i,\\; p_i^{*}(\\theta\\Delta r) < \\bar{p}_i\\}

Planned public interface
------------------------
- ``clear(network, capacities, *, max_iter, tol) -> ClearingVector``
- ``breaking_point(network, capacities, shock_spec, *, tol) -> BreakingPoint``
"""
