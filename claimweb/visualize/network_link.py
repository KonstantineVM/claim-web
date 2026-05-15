"""Interactive node-link diagram (project plan Part VII).

Built on pyvis. Supports zoom from sector aggregation through entity
granularity down to legal-entity granularity. Toggleable overlays for
G2 (regulatory coverage) and G3 (ownership clusters).

Planned public interface
------------------------
- ``render_node_link(network, *, period, output_path, overlay=None)
  -> NodeLinkFigure``
"""
