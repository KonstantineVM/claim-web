"""Claim-multiplier time-series renderer (project plan §22 Output 2).

Line charts of the claim multiplier — system-wide and per ownership
cluster — with uncertainty bands derived from the ME/MD reconstruction
bracket.

Planned public interface
------------------------
- ``render_multiplier_series(multiplier_panel, *, output_path)
  -> MultiplierTimeSeriesFigure``
"""
