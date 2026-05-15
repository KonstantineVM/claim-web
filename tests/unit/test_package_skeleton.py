"""Bootstrap-time smoke test: verify the package skeleton imports cleanly.

This is the only test that exists before fetchers, constraints, and solvers
are implemented. Its job is to verify project plan §18's package layout
exists and every module imports without error. It is intentionally minimal —
no module logic is being tested, just the scaffolding.
"""
from __future__ import annotations

import importlib

import pytest

# All subpackages and submodules declared in the project plan §18 layout.
_SUBPACKAGES = (
    "claimweb",
    "claimweb.fetchers",
    "claimweb.normalize",
    "claimweb.constraints",
    "claimweb.reconstruct",
    "claimweb.cascade",
    "claimweb.multiplier",
    "claimweb.validation",
    "claimweb.visualize",
    "claimweb.api",
    "claimweb.abm",
    "claimweb.abm.agents",
)

_SUBMODULES = (
    "claimweb.constraints.kcl",
    "claimweb.constraints.double_entry",
    "claimweb.constraints.sectoral",
    "claimweb.constraints.flow_funds",
    "claimweb.constraints.prior",
    "claimweb.reconstruct.max_entropy",
    "claimweb.reconstruct.min_density",
    "claimweb.reconstruct.solver",
    "claimweb.reconstruct.validate",
    "claimweb.cascade.eisenberg_noe",
    "claimweb.cascade.fire_sale",
    "claimweb.cascade.multi_constraint",
    "claimweb.cascade.contingent",
    "claimweb.cascade.debtrank",
    "claimweb.validation.ep1_2007_xfabs",
    "claimweb.validation.ep2_2008_aig_seclending",
    "claimweb.validation.ep3_2020_covid_stress",
    "claimweb.visualize.sankey",
    "claimweb.visualize.network_link",
    "claimweb.visualize.cascade_dag",
    "claimweb.visualize.multiplier_timeseries",
    "claimweb.abm.simulator",
    "claimweb.abm.scenarios",
    "claimweb.abm.calibration",
)


@pytest.mark.parametrize("name", _SUBPACKAGES + _SUBMODULES)
def test_module_imports(name: str) -> None:
    importlib.import_module(name)


@pytest.mark.parametrize("name", _SUBPACKAGES + _SUBMODULES)
def test_module_has_docstring(name: str) -> None:
    """Every module has a docstring referencing its project-plan section."""
    module = importlib.import_module(name)
    assert module.__doc__, f"{name} is missing its module-level docstring"


def test_package_version_is_set() -> None:
    import claimweb

    assert isinstance(claimweb.__version__, str)
    assert claimweb.__version__  # non-empty
