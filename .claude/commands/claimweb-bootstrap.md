---
description: Bootstrap the CLAIM-WEB Python package skeleton. Run this in the first session of the project.
argument-hint: (none)
---

# /claimweb-bootstrap

Scaffold the CLAIM-WEB Python package per project plan §18. This is the first concrete piece of work after the harness is in place.

## What to do

1. **Check current state.** Run `bash scripts/setup.sh` first to verify the environment. If it reports missing prerequisites, stop and surface them to the user.

2. **Read the relevant plan sections.** Specifically:
   - `docs/CLAIM_WEB_PROJECT_PLAN.md` §18 (Codebase architecture)
   - `docs/CLAIM_WEB_PROJECT_PLAN.md` §19 (Dependencies)
   - `docs/CLAIM_WEB_PROJECT_PLAN.md` §21 (Testing discipline)

3. **Create the package skeleton.** Under the project root, create:
   ```
   claimweb/
     __init__.py
     fetchers/__init__.py
     normalize/__init__.py
     constraints/__init__.py
       kcl.py            # Law 1 — placeholder with docstring referencing project plan §1.1
       double_entry.py   # Law 2
       sectoral.py       # Law 3
       flow_funds.py     # Law 4
       prior.py
     reconstruct/__init__.py
       max_entropy.py
       min_density.py
       solver.py
       validate.py
     cascade/__init__.py
       eisenberg_noe.py
       fire_sale.py
       multi_constraint.py
       contingent.py
       debtrank.py
     multiplier/__init__.py
     validation/__init__.py
       ep1_2007_xfabs.py
       ep2_2008_aig_seclending.py
       ep3_2020_covid_stress.py
     visualize/__init__.py
       sankey.py
       network_link.py
       cascade_dag.py
       multiplier_timeseries.py
     api/__init__.py
     abm/                 # see project plan Part XII
       __init__.py
       agents/__init__.py
       simulator.py
       scenarios.py
       calibration.py

   tests/
     __init__.py
     unit/
       __init__.py
     integration/
       __init__.py
     validation/
       __init__.py
     conftest.py

   data/
     raw/.gitkeep
     normalized/.gitkeep
     output/.gitkeep

   notebooks/
     .gitkeep

   pyproject.toml
   .gitignore
   ```

   Every `.py` module file should be a real file with at minimum a module-level docstring that:
   - States the module's purpose in one sentence
   - References the project-plan section that specifies it
   - Lists the public functions/classes it will eventually expose (as a TODO list)

   Do NOT implement the modules yet. The scaffolding is the unit of work.

4. **pyproject.toml.** Per project plan §19, dependencies are: `numpy`, `scipy`, `pandas`, `networkx`, `cvxpy`, `pyarrow`, `statsmodels`, `scikit-learn`, `matplotlib`, `plotly`, `pyvis`, `httpx`, `requests`, `beautifulsoup4`, `pdfplumber`, `tabula-py`, `lxml`. Test deps: `pytest`, `hypothesis`. Optional dev: `ruff`, `mypy`. Pin to specific versions consistent with current PyPI releases.

5. **.gitignore.** Standard Python ignore plus:
   - `data/raw/` (large; archived separately)
   - `data/output/network/*/v*/` except v0 placeholder
   - `.claude/session-log/`
   - `.claude/.last_gate_run`

6. **Verify scaffolding.** Run:
   - `python -m py_compile $(find claimweb -name '*.py')` — every file should compile
   - `pytest tests/ --collect-only` — should report 0 tests but no errors
   - `bash scripts/precommit_gate.sh` — should pass (or warn only on missing tests)

7. **Update state files.**
   - Append a CHANGELOG.md entry titled "Bootstrap: package skeleton" describing what was created.
   - Update TODO.md: move the bootstrap item from "Now" to "Done"; promote the first fetcher (`claimweb.fetchers.fhlb_combined`) from "Next" to "Now".

8. **Commit and push.** One commit: "claimweb: package skeleton". Reference the project plan §18 in the commit body.

## What not to do

- Do not start implementing fetchers, solvers, or anything beyond docstring stubs in this bootstrap. Implementation of any single module deserves its own focused session.
- Do not add dependencies beyond the project-plan §19 list without flagging to the user.
- Do not skip the docstring requirement — those docstrings are the package's first-pass interface contract.
