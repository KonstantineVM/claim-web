"""Sankey diagram renderer (project plan §22 Output 4).

For each period, renders a Sankey of the network with:

- arcs sized by dollar volume
- nodes color-coded by ownership cluster
- node shading by real-dollar-capacity ratio
- arc color-coding per ``DataQualityFlag``

Built in Plotly with an optional interactive D3 variant. Supports
time-slider navigation across 2000-Q1 through current.

Planned public interface
------------------------
- ``render_sankey(network, *, period, output_path, interactive=False)
  -> SankeyFigure``
"""
