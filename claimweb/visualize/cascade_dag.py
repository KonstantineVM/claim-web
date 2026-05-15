"""Cascade-DAG renderer for cascade-simulation results
(project plan §22 Output 3).

Renders the directed-acyclic-graph of cascade events for a given
``(period, shock_specification)`` pair. Each node is an entity; each
edge is a propagation step. Time on the y-axis (top = first event).

Planned public interface
------------------------
- ``render_cascade_dag(cascade_result, *, output_path) -> CascadeDAGFigure``
"""
