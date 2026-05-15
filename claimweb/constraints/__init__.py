"""Conservation-law constraint compilation (project plan §1.1, §13 Phase B).

Four hard laws plus one soft regularizer. Each module emits rows of a
sparse linear constraint system consumed by ``claimweb.reconstruct``.

Modules
-------
- ``kcl``           Law 1: balance-sheet identity at each node
- ``double_entry``  Law 2: instrument-level holdings = issuances
- ``sectoral``      Law 3: Z.1 sectoral aggregate boundary conditions
- ``flow_funds``    Law 4: transactions-vs-positions reconciliation
- ``prior``         entity-type compatibility (soft regularizer)
- ``compile``       aggregator that emits the full sparse linear system

Per CLAUDE.md standing rule: these are *invariants*, not targets. A solved
network violating any of them is a bug.

Planned public interface
------------------------
- ``check_network(network_dir) -> CheckResult`` — driver used by
  ``scripts/check_conservation.py``.
"""
