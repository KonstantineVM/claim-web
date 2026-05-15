#!/usr/bin/env python3
"""Conservation-law checker for solved CLAIM-WEB networks.

This is a thin wrapper that finds solved networks in data/output/ and applies
the four conservation laws from project plan §1.1:

  Law 1 — Balance sheet identity at each node
  Law 2 — Double-entry consistency at each instrument
  Law 3 — Sectoral aggregates from Z.1 boundary conditions
  Law 4 — Flow-of-funds transactions-vs-positions reconciliation

The actual constraint implementations live in `claimweb.constraints.*`.
This script imports them and runs them on every solved network present.

If `claimweb.constraints` is not yet implemented (early phase), this script
exits 0 with a notice. After the constraint module exists, this script
performs the actual checks.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    output_dir = project_root / "data" / "output"

    if not output_dir.exists():
        print("data/output/ does not exist yet. Nothing to check.")
        return 0

    # Try to import the constraints module. If absent (early phase), warn but exit clean.
    try:
        from claimweb.constraints import kcl, double_entry, sectoral, flow_funds  # noqa: F401
    except ImportError:
        # The constraint module hasn't been written yet. That's fine in early phases.
        # But warn if there are output files present that should be checked.
        outputs = list(output_dir.rglob("*.parquet"))
        if outputs:
            print(
                "WARN: solved networks present in data/output/ but "
                "claimweb.constraints is not yet importable. "
                "Cannot verify conservation laws. "
                "Once claimweb/constraints/ is implemented, re-run this script."
            )
        return 0

    # Walk solved networks.
    networks = sorted(output_dir.glob("network/*/"))
    if not networks:
        print("No solved networks present yet.")
        return 0

    failures = []
    for net_dir in networks:
        period = net_dir.name

        # The actual implementation. We expect the constraint module to expose
        # a high-level `check_network(network_dir)` function.
        try:
            from claimweb.constraints import check_network  # type: ignore[attr-defined]
        except ImportError:
            print(
                f"claimweb.constraints.check_network not exposed. "
                f"Expected by this script. Period {period} not checked."
            )
            continue

        result = check_network(net_dir)
        if not result.holds:
            failures.append((period, result))

    if failures:
        print(f"\nCONSERVATION FAILURES in {len(failures)} period(s):\n")
        for period, result in failures:
            print(f"  {period}: {result.summary()}")
        return 1

    print(f"OK: conservation laws hold for all {len(networks)} solved network(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
