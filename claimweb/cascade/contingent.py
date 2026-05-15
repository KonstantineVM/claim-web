"""Banerjee-Feinstein contingent-payment cascade
(Banerjee-Feinstein 2019; project plan §15).

Extends Eisenberg-Noe to contingent payments — CDS, and certain
reinsurance contracts where payment to the cedent is contingent on the
cedent's underlying liability development rather than a fixed face
amount.

Used in CLAIM-WEB primarily for the offshore reinsurance arc, where the
contingent structure changes the cedent's recovery rate in a cascade.

Planned public interface
------------------------
- ``clear_with_contingent(network, capacities, contingencies, *,
                          max_iter, tol) -> ClearingVectorWithContingency``
"""
