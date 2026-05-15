"""Episode 1 — 2007 extendible-ABCP (XFABS) run (project plan §17).

Reconstruct the U.S. financial network for 2007-Q2 (pre-run) and
2007-Q4 (post-run). Apply a redemption shock at the XFABS-conduit entry
nodes. The clearing-vector cascade must reproduce the observed ~$18B run
within tolerance, with the bank-sponsor liquidity providers absorbing
the shock at magnitudes consistent with the historical record.

Planned public interface
------------------------
- ``run_episode_1(network_2007q2, network_2007q4) -> EpisodeResult``
"""
