---
name: validation-author
description: Author or modify validation tests under tests/validation/. Use when constructing or refining the historical-retrodiction tests for 2007 XFABS, 2008 AIG sec-lending, or March 2020 prime MMF/repo stress. Triggers on phrases like "validation test", "retrodiction", "historical episode", "XFABS run", "AIG sec-lending", "March 2020 stress", "episode 1/2/3". Encodes how the deployment gate is implemented.
---

# Authoring a validation test

The three historical retrodiction episodes are the project's deployment gate (project plan §17). A model that cannot retrodict 2007, 2008, and 2020 within tolerance does not get deployed. The validation tests live in `tests/validation/` and are the executable form of the gate.

## File organization

`tests/validation/` contains:

- `__init__.py`
- `ep1_2007_xfabs.py`
- `ep2_2008_aig_seclending.py`
- `ep3_2020_covid_stress.py`
- `conftest.py` — shared fixtures (pre-shock network states, asset-liquidity calibrations)
- `historical_facts.py` — the canonical historical-target data (peer-reviewed citations only)
- `tolerances.py` — the project-plan-specified tolerance bands

## Episode targets and tolerances

Codified in `tolerances.py`:

```python
EPISODE_1_TARGET = HistoricalTarget(
    period="2007-Q2",
    shock=ShockSpec(
        instrument="A2_XFABS",
        magnitude_pct=1.00,
        affected_arcs="institutional_holders_to_xfabs_issuing_spvs",
    ),
    historical_aggregate_loss_billions=Decimal("18"),
    historical_loss_tolerance_pct=Decimal("0.30"),
    historical_affected_entities=frozenset({"HARTFORD_LIFE", "ING_USA_LIFE", "MET_LIFE", "PRU_LIFE", "AIG_SUNAMERICA"}),
    minimum_overlap_count=4,
    citation="Foley-Fisher, Narajabad, Verani (2020), JPE 128(9):3520-3569",
)

EPISODE_2_TARGET = HistoricalTarget(...)
EPISODE_3_TARGET = HistoricalTarget(...)
```

All historical-target numbers come from peer-reviewed sources. Never from press articles or industry commentary. If a number isn't in the cited paper, it doesn't go in tolerances.py.

## Test structure

Each episode is one pytest test. Skeleton:

```python
import pytest
from claimweb.cascade import simulate_cascade
from claimweb.io import load_solved_network
from tests.validation.tolerances import EPISODE_1_TARGET as TARGET

@pytest.mark.validation
def test_episode_1_2007_xfabs_run():
    """Retrodict the 2007 XFABS run.

    Tolerance: ±30% on aggregate loss; affected entities overlap >= 4.
    Pre-shock state: 2007-Q2 solved network.

    Reference: Foley-Fisher, Narajabad, Verani (2020) JPE.
    Project plan: §17.
    """
    pre_state = load_solved_network(TARGET.period)

    cascade = simulate_cascade(
        network=pre_state,
        shock=TARGET.shock,
        config=production_cascade_config(),
    )

    # Aggregate loss check
    aggregate_loss = cascade.aggregate_loss_billions
    historical = TARGET.historical_aggregate_loss_billions
    tolerance = TARGET.historical_loss_tolerance_pct
    assert abs(aggregate_loss - historical) / historical <= tolerance, (
        f"Aggregate loss {aggregate_loss}B outside ±{tolerance*100}% of historical {historical}B"
    )

    # Affected-entity overlap check
    predicted_entities = {e for e, loss in cascade.per_entity_loss.items() if loss > 0}
    overlap = len(predicted_entities & TARGET.historical_affected_entities)
    assert overlap >= TARGET.minimum_overlap_count, (
        f"Predicted entities overlap only {overlap} with historical "
        f"(need >= {TARGET.minimum_overlap_count}); "
        f"predicted: {predicted_entities}, historical: {TARGET.historical_affected_entities}"
    )

    # Write retrodiction report
    write_retrodiction_report(
        episode=1,
        cascade=cascade,
        target=TARGET,
        path=f"docs/validation/{date_today_iso()}_episode_1.md",
    )
```

## The retrodiction report

Every successful (and failing) test run writes a markdown report under `docs/validation/`. The format is in the documentation-curator subagent's spec; here we just emit it.

The report must include:
- Methodology version (commit hash at test run)
- Pre-shock network state (period, ME/MD bracket summary, conservation-check status)
- Shock specification applied (instrument, magnitude, affected arcs)
- Cascade output (aggregate loss with bracket, per-entity losses sorted, cascade DAG)
- Comparison against target (per-tolerance pass/fail)
- If failed: candidate causes (which extension was binding, where the discrepancy concentrated)

## Methodology-version locking

Validation tests pass or fail against a specific methodology version. When the methodology is amended (per project plan §48), the validation must be re-run; if any episode no longer passes, the amendment is rolled back or the methodology is re-parameterized until passing.

The conftest.py exposes a fixture that records the methodology version (commit hash + manual amendment number) at test start. The retrodiction report includes this so a future reader can identify exactly which version was being validated.

## The "no parameter-tuning to fit" discipline

The validation tests must not be allowed to drive parameter overfitting. The discipline:
1. The cascade parameters (recovery rates, fire-sale price-impact coefficients, etc.) are set from the published literature, not from making the validation pass.
2. If validation fails, the failure is information — it means a *structural* choice (cascade rule, runnability classification) is wrong, not a parameter that needs adjustment.
3. Re-parameterization within published parameter ranges (e.g., choosing within the Greenwood-Landier-Thesmar 2015 reported range for a price-impact parameter) is acceptable; re-parameterization outside published ranges to make the validation pass is overfitting and not permitted.
4. The methodology paper documents the parameter choices and their justification (which paper, which range, why this point estimate).

## What not to do

- Do not adjust the tolerance bands. The tolerances come from project plan §17 and represent a deliberate epistemic stance about model fidelity.
- Do not silently change the historical-target numbers. If a new published paper updates a historical estimate, that's a methodology amendment and requires user authorization.
- Do not commit a "now passing" change without writing the retrodiction report.
- Do not introduce methodology changes that pass validation but fail the conservation-law checker. The constraints come first.
