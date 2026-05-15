"""Maximum-entropy network reconstruction (Upper 2004; project plan §13).

Given marginal row and column sums of the bilateral exposure tensor
(from per-entity balance-sheet totals and Z.1 sectoral aggregates), the
maximum-entropy reconstruction is the unique solution that maximizes

.. math::

    H(X) = -\\sum_{ij,k} x_{ij}^{k} \\log x_{ij}^{k}

subject to the linear constraints from Laws 1–4 and any direct
observations. Convex; solved by RAS / iterative proportional fitting.

A reference implementation exists in R (``NetworkRiskMeasures``); we
re-implement in Python on top of ``scipy`` + ``cvxpy``. Before coding,
spawn the ``literature-checker`` subagent against Upper (2004).

Planned public interface
------------------------
- ``solve_max_entropy(system, *, max_iter, tol) -> SolvedNetwork``
"""
