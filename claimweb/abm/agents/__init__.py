"""Agent classes for the ABM (project plan §39).

One module per node class from §3. Each agent class exposes a
``decision_rule(state, events) -> actions`` method.

Planned agent modules
---------------------
- ``saver``         ``SaverAgent`` (M1, M2)
- ``bank_treasury`` ``BankTreasuryAgent`` (M3, I4)
- ``mmf``           ``MMFAgent`` (I1)
- ``spv``           ``SPVAgent`` (I2, pass-through)
- ``fhlb``          ``FHLBAgent`` (I3)
- ``dealer``        ``DealerAgent`` (I4)
- ``custodian``     ``CustodianAgent`` (I5)
- ``aam``           ``AAMAgent`` (I6, I7)
- ``bdc``           ``BDCAgent`` (I8)
- ``insurer``       ``InsurerAgent`` (T1)
- ``reinsurer``     ``ReinsurerAgent`` (T2)
- ``borrower``      ``BorrowerAgent`` (T3)
"""
