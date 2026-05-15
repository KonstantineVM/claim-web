"""Episode 2 — 2008 AIG securities-lending collapse (project plan §17).

Reconstruct 2008-Q2 and 2008-Q3. Apply the sec-lending collateral-call
shock to AIG's portfolio. The cascade must reproduce:

- collateral-call escalation against AIG
- the path to federal intervention (~$85B initial Fed credit line)
- loss-allocation across counterparties consistent with the public record

Planned public interface
------------------------
- ``run_episode_2(network_2008q2, network_2008q3) -> EpisodeResult``
"""
