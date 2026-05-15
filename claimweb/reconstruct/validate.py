"""Internal consistency checks on the reconstructed network
(project plan §13).

Run after reconstruction and before output emission. Verifies:

- every conservation law (Laws 1–4) holds within tolerance
- every arc carries a ``DataQualityFlag``
- the ME/MD bracket does not collapse to a single point in
  unobserved regions (would indicate a constraint-matrix bug)
- entity-type compatibility (prior) violations are documented

Planned public interface
------------------------
- ``validate_reconstruction(bracketed_network) -> ValidationReport``
"""
