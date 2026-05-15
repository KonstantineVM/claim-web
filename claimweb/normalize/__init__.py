"""Schema normalization for fetched arc facts (project plan §11).

Converts the heterogeneous fetcher outputs into the canonical ``ArcFact``
schema with explicit ``DataQualityFlag`` provenance per CLAUDE.md standing
rule.

Planned modules
---------------
- ``arc_fact``       canonical schema and Parquet I/O
- ``quality_flag``   data-quality-flag taxonomy
                     (``DIRECT_MEASURED``, ``MARGINAL_INFERRED``,
                     ``DOUBLE_ENTRY_INFERRED``, ``SECTORAL_DISAGGREGATED``,
                     ``PROXY``, ``MODEL_ESTIMATE``, ``UNOBSERVED``)
- ``entity_map``     legal-entity identifier mapping
                     (LEI ↔ CIK ↔ NAIC ↔ CRD)
- ``instrument_map`` instrument-class taxonomy (per §3 node taxonomy)
"""
