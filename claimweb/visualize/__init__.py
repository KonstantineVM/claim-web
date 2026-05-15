"""Output rendering (project plan Part VII).

Modules
-------
- ``sankey``                 Plotly Sankey + D3 interactive variant
                             (Output 4 per §22)
- ``network_link``           pyvis interactive node-link diagram
- ``cascade_dag``            directed-acyclic-graph rendering of cascade
                             trajectories
- ``multiplier_timeseries``  line charts with uncertainty bands

All renderers respect the data-quality-flag color coding specified in
``.claude/rules/data-quality-flags.md``.
"""
