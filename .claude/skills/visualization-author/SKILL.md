---
name: visualization-author
description: Author or modify visualization modules under claimweb/visualize/. Use when implementing the Sankey renderer, node-link renderer, cascade-DAG renderer, multiplier time-series renderer, or web product components. Triggers on phrases like "Sankey", "render the network", "visualization", "node-link diagram", "cascade DAG", "web product", "frontend", "D3", "Plotly". Encodes the visualization conventions and the data-quality-flag color coding.
---

# Authoring a visualization

CLAIM-WEB's outputs need to be legible to three audiences: academic peer reviewers (precise, reproducible), regulators (clear, navigable), and the financial press / public (compelling, drillable). The visualization layer serves all three.

## File organization

`claimweb/visualize/` contains:

- `sankey.py` — Sankey diagram of the from-whom-to-whom matrix per period
- `network_link.py` — Force-directed node-link diagram with ownership-cluster grouping
- `cascade_dag.py` — DAG of cascade propagation per shock scenario
- `multiplier_timeseries.py` — Claim-multiplier time series with uncertainty bands
- `style.py` — Color palette, font conventions, data-quality-flag color coding
- `web/` — Interactive web product (React + D3 frontend; FastAPI backend for cascade-on-demand)

## Mandatory style conventions

### Color coding by data-quality flag

The flag must be visible. Color palette (colorblind-safe):

- `DIRECT_MEASURED` → `#2E7D32` (deep green)
- `DOUBLE_ENTRY_INFERRED` → `#66BB6A` (medium green)
- `MARGINAL_INFERRED` → `#FBC02D` (yellow)
- `SECTORAL_DISAGGREGATED` → `#FB8C00` (orange)
- `PROXY` → `#E64A19` (red-orange)
- `MODEL_ESTIMATE` → `#C62828` (red)
- `UNOBSERVED` → `#9E9E9E` (gray, dashed line)

Every visualization that shows arcs displays this color coding. A legend is always present.

### Color coding by ownership cluster (G3 overlay)

When ownership clusters are shown:

- Apollo cluster → `#3F51B5` (indigo)
- Blackstone cluster → `#000000` (black)
- KKR cluster → `#D32F2F` (red)
- Brookfield cluster → `#388E3C` (green)
- Carlyle cluster → `#7B1FA2` (purple)
- Independent insurer → `#607D8B` (blue-gray)

Toggle between G2 (regulatory coverage) and G3 (ownership) overlays is a first-class UI control.

### Typography

- Headings: Inter (web-safe sans-serif)
- Numbers in tables: tabular figures via `font-variant-numeric: tabular-nums`
- Code/identifiers: JetBrains Mono

### Unit conventions

- Dollar amounts: always shown in billions or millions, never raw dollars
- Period labels: ISO format `YYYY-QN` for quarterly, `YYYY-MM` for monthly
- Tooltips always show the underlying value with full precision

## Per-module specifications

### Sankey diagram (sankey.py)

Built on Plotly's Sankey. Source nodes on the left, instruments in the middle, target nodes on the right (or arranged as a multi-layer flow when the chain has more than three layers).

Required interactions:
- Hover on a link → show source, target, instrument, dollar amount, data-quality flag, bracket (if applicable)
- Click on a node → drill down to that node's full arc set in a side panel
- Time slider → animate across periods 2000-Q1 to current

Output: one HTML file per quarter for static archives; one shared interactive HTML with the time slider for the live web product.

### Node-link diagram (network_link.py)

Built on D3 force-directed layout (web product) or PyVis (static archives).

- Node size: total assets at the node (with logarithmic scaling — life insurer general accounts dwarf BDCs by orders of magnitude)
- Node color: data-quality flag aggregated across the node's arcs
- Edge thickness: dollar volume
- Edge color: data-quality flag of that arc
- Ownership-cluster boundaries shown as soft convex hulls when G3 overlay is enabled
- Regulator boundaries shown as a separate overlay (G2)

Required interactions: zoom, pan, drill from sector aggregation to entity to legal entity.

### Cascade DAG (cascade_dag.py)

For each shock scenario, render the cascade as a directed acyclic graph: source shock at the top, propagation downward, failed nodes in red, distressed-but-not-failed nodes in orange, intermediate edges labeled with the cause (direct counterparty default vs fire-sale loss vs regulatory-trigger breach).

The DAG must show the time-ordering of induced defaults (which node failed when due to which other node's failure). The y-axis is iteration count of the cascade simulator; the x-axis is the network's broader structure (clustered by ownership).

### Multiplier time series (multiplier_timeseries.py)

Line charts with uncertainty bands. The y-axis is the claim multiplier $M(t)$; the x-axis is time 2000-Q1 to current. Multiple series can be overlaid:

- System multiplier (line, navy)
- Per-cluster multipliers (lighter lines colored by cluster)
- Per-instrument-class multipliers (separate panel)

The bracket between ME and MD estimates is rendered as a translucent band around each line.

## The web product

Architecture per project plan §24: static-site-generation + server-side cascade-API hybrid.

- **Frontend** in React + D3, served from CDN. The dataset is pre-computed and shipped as static Parquet + JSON.
- **Backend** in FastAPI, deployed to a stable host. The backend serves cascade simulations on demand — when a user specifies a custom shock that isn't in the pre-computed set, the backend runs the simulator with caching.
- **Endpoints**:
  - `GET /api/network/{period}` — return the solved network for the period
  - `GET /api/cascade/{period}/{shock_id}` — return a pre-computed cascade result
  - `POST /api/cascade/custom` — run an on-demand cascade for a user-specified shock
  - `GET /api/multiplier/{filter}` — return the claim multiplier time series

The web/ directory mirrors project plan §24's feature list:
- Browse the network at any quarter
- Toggle between Sankey and node-link
- Zoom from sector to legal entity
- Overlay G2 / G3
- Filter by instrument class, entity, AAM cluster
- Custom shock builder
- Drill-down on any arc
- Download any subset as CSV
- Historical retrodiction overlay

## Testing

- **Snapshot tests** for visualization outputs. Render a known fixture network; compare the SVG/JSON output to a committed reference. Tolerate timestamps and ID-generation but not data values.
- **Accessibility tests** (axe-core) for the web product. Color contrast must pass WCAG AA.
- **Performance tests**: the Sankey for the largest quarter (~3000 arcs) must render in <2 seconds on a typical browser.

## What not to do

- Do not invent color palettes. The palette is fixed (data-quality flags and ownership clusters). Adding new colors requires a methodology amendment.
- Do not omit the data-quality color legend. Every visualization must show it; this is non-negotiable for project credibility.
- Do not pre-aggregate in a way that hides individual entity behavior. Aggregation is a user choice, not a default; users zoom up to aggregate when they want, not down from a forced aggregation.
- Do not embed copyrighted images (regulator logos, etc.) without explicit clearance. Use plain-text labels.
