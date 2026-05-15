"""Pre-defined ABM crisis scenarios (project plan §41–§42).

Mirrors the three historical-validation episodes from §17 plus
parameterized forward scenarios.

Planned scenarios
-----------------
- ``scenario_2007_xfabs``   2007 XFABS run
- ``scenario_2008_aig``     2008 AIG sec-lending collapse
- ``scenario_2020_covid``   March 2020 prime-MMF / repo stress
- ``scenario_forward_redemption_shock(magnitude, entry_nodes)``

Planned public interface
------------------------
- ``Scenario(name, events, horizon)``
"""
