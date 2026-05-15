"""Historical retrodiction — gates deployment (project plan §17).

Three episodes; all must pass within tolerance before any forward-use
claim is published.

Modules
-------
- ``ep1_2007_xfabs``           2007 extendible-ABCP (XFABS) run
- ``ep2_2008_aig_seclending``  2008 AIG securities-lending collapse
- ``ep3_2020_covid_stress``    March 2020 prime-MMF / repo stress

Per CLAUDE.md standing rule: historical validation is the deployment gate.
A model that fails to retrodict 2007, 2008, or 2020 is not deployed.
"""
