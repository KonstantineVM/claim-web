"""Query / drill-down API (project plan Part VIII).

Powers the interactive web product. Read endpoints expose the network at
any quarter, per-entity holdings, and per-instrument propagation paths;
write endpoints accept cascade-scenario submissions.

Planned modules
---------------
- ``query``     read endpoints (network, entity, instrument)
- ``scenario``  write endpoints (cascade-scenario submission)
- ``server``    FastAPI app composing the above
"""
