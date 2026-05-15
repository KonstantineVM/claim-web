"""Minimum-density network reconstruction
(Anand-Craig-von Peter 2015; project plan §13).

Seeks the *sparsest* feasible network satisfying the linear constraints
from Laws 1–4. Empirically, real financial networks are far sparser than
the maximum-entropy estimate predicts; ME and MD bracket the true network
from above (ME) and below (MD).

Combinatorial problem; relaxed via the Anand-Craig-von Peter iterative
algorithm — assign edges greedily to satisfy marginals, iterate to
convergence. Before coding, spawn the ``literature-checker`` subagent
against Anand, Craig, and von Peter (2015) *Quantitative Finance*
15(4):625–636.

Planned public interface
------------------------
- ``solve_min_density(system, *, max_iter, tol) -> SolvedNetwork``
"""
