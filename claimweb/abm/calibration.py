"""ABM parameter calibration from historical data (project plan §41).

Calibrates decision-rule parameters from the published empirical
literature:

- Greenwood-Landier-Thesmar (2015) — LCR-targeting behavior
- Schmidt-Timmermann-Wermers (2016), Cipriani-La Spada-Mulder (2023) —
  MMF investor redemption response
- Brunnermeier-Pedersen (2009) — dealer haircut / margin-spiral framework
- Sen (2023) — variable-annuity hedging program response
- public lapse-experience studies — insurer surrender behavior

Planned public interface
------------------------
- ``calibrate(historical_periods, *, method="mle") -> CalibratedParameters``
"""
