"""Battiston DebtRank centrality overlay
(Battiston et al. 2012; project plan §15, §16).

DebtRank is a feedback-centrality measure of systemic importance that
captures distress propagation even without default. Identifies nodes
whose stress propagates most widely — not only those that default
outright.

DebtRank is computed on the solved network and runs in *parallel* with
clearing-vector analysis, not in sequence. It does not consume clearing
output as input.

Planned public interface
------------------------
- ``compute_debtrank(network, *, shock_vector) -> DebtRankResult``
"""
