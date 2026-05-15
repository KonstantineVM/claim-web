"""Soft entity-type compatibility constraints (project plan §1.2, §13 Phase B).

Hard constraints come from Laws 1–4. Prior knowledge — an SPV holds at
most one funding agreement, an MMF must satisfy Rule 2a-7, an FHLB
advance is collateralized by member-pledged eligible collateral — enters
as a regularizer in the reconstruction objective. Not enforced as an
equality; biases the solver away from infeasible-in-practice solutions.

Planned public interface
------------------------
- ``entity_type_compatibility(entity, instrument) -> float``
- ``build_prior_regularizer(facts, *, period) -> RegularizerTerm``
"""
