"""CLAIM-WEB test suite root (project plan §21).

Three tiers:

- ``unit/``        per-module unit tests; property-based via ``hypothesis``
                   for the four conservation laws
- ``integration/`` synthetic-network sanity checks against computable
                   answers
- ``validation/``  three historical-retrodiction episodes (§17); the
                   deployment gate

Coverage target: 95%+ on ``claimweb/`` analytical modules. Fetchers
tolerate lower coverage because external data sources cannot be fully
mocked.
"""
