"""Reconstruction harness — runs both ME and MD and brackets the spread
(project plan §13).

Pipeline
--------
1. Compile the constraint system from ``claimweb.constraints``
2. Run the maximum-entropy solver
3. Run the minimum-density solver
4. Report per-arc the ``(ME, MD)`` bracket as a structural-uncertainty band
5. Flag arcs whose bracket exceeds a configurable tolerance for review

Per CLAUDE.md standing rule: both reconstruction methods run, with bracket
reported per arc. Any output collapsing the bracket to a point in
unobserved regions indicates a constraint-matrix bug.

Planned public interface
------------------------
- ``reconstruct(facts, *, period, methods=("max_entropy", "min_density"))
  -> BracketedNetwork``
"""
