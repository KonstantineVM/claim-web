---
description: Data-quality-flag taxonomy and assignment rules. Applies anywhere ArcFacts are emitted or transformed. Required reading before authoring a fetcher or modifying a solver.
paths:
  - claimweb/fetchers/**
  - claimweb/normalize/**
  - claimweb/reconstruct/**
  - claimweb/constraints/**
---

# Data-quality flags

Every `ArcFact` carries one of seven flags. The flag travels with the arc through every downstream computation; consumers (visualization, web product, downstream analysis) display the flag so users know how trustworthy each arc is.

Project plan §12 defines the flags; this rule operationalizes the assignment.

## The seven flags

### `DIRECT_MEASURED`

The arc value comes from a direct, unambiguous disclosure in an origin source. Examples:
- An insurer's 10-Q explicitly discloses `AdvancesFromFederalHomeLoanBanks` as a line item with a single value → that arc to the FHLB district is `DIRECT_MEASURED`.
- A MMF's Form NMFP lists CUSIP-by-CUSIP holdings, including specific FABN issuances → the arc from MMF to SPV is `DIRECT_MEASURED`.
- An FHLB's 10-K lists named members in its top-10 advance-holders table with specific dollar amounts → that arc is `DIRECT_MEASURED`.

Required: the source filing, page/section, and specific field are recorded in `provenance_*` on the ArcFact.

### `MARGINAL_INFERRED`

The arc value is solved from Law 1 (balance-sheet identity) given measured row/column sums. Example: an entity discloses total liabilities and discloses every liability instrument except one; the unmeasured instrument's value is fully determined by the row sum. That arc is `MARGINAL_INFERRED`.

Recording: the entity, period, and the specific identity used to infer.

### `DOUBLE_ENTRY_INFERRED`

The arc value is solved from Law 2 (double-entry consistency) given that the other side is `DIRECT_MEASURED`. Example: an MMF discloses holding $5B of a specific SPV's FABN; the SPV's liability side then has a fully-determined $5B arc to that MMF (not to any other MMF). `DOUBLE_ENTRY_INFERRED`.

This flag is *higher quality than `MARGINAL_INFERRED`* because the double-entry is exact, not residual. Use this flag whenever one side of the arc is directly measured even if the other side has multiple possibilities; the law forces the other side to match.

### `SECTORAL_DISAGGREGATED`

The arc value is disaggregated from a Z.1 sectoral total using the maximum-entropy / minimum-density estimator. Example: Z.1 publishes total FABN holdings by the MMF sector; the per-MMF disaggregation comes from the ME/MD reconstruction. Every arc emerging from sectoral disaggregation is flagged `SECTORAL_DISAGGREGATED`.

Required: the ME value, the MD value, and the bracket. These are stored on the ArcEstimate (per `reconstruction-author` skill), not the ArcFact, but the flag links them.

### `PROXY`

The arc is estimated from a closely related instrument or a published proxy series. Example: total Level 2 HQLA at a bank is used as a proxy for that bank's FABS holdings; private credit fund AUM is used as a proxy for the BDC-to-borrower arc volume. Always documented; always flagged.

Required: the proxy series, the calibration method, the cited justification.

### `MODEL_ESTIMATE`

The arc value is derived from a calibrated model with documented assumptions. Example: variable annuity contingent liabilities valued via Koijen-Yogo (2022) framework with specific equity-market assumptions; insurer recapture-trigger exposures modeled from treaty terms. Always documented; always flagged.

Required: the model specification, the parameters used, the citation. Methodology amendment governance (per project plan §48) applies to any change in model specification.

### `UNOBSERVED`

The arc is *not* in the dataset. This flag exists so users can distinguish "we measured zero" from "we didn't measure". The arc is reported as missing with a structured reason: "no Schedule S disclosure for this period", "Bermuda registry does not cover this entity", "Z.1 series begins later than this period". Never silently set to zero.

Required: the specific reason. Aggregations (claim multipliers, breaking points) treat `UNOBSERVED` arcs as missing data, not as zero — and report the missingness in the output.

## Assignment priority

When an arc could be assigned multiple flags, use the highest-quality flag for which the data supports it. Priority order, best to worst:

```
DIRECT_MEASURED
  > DOUBLE_ENTRY_INFERRED
    > MARGINAL_INFERRED
      > SECTORAL_DISAGGREGATED
        > PROXY
          > MODEL_ESTIMATE
            > UNOBSERVED
```

If a fetcher could emit an arc as `DIRECT_MEASURED` but the alternative is `PROXY`, use `DIRECT_MEASURED`. The exception: if direct measurement is ambiguous (e.g., a disclosure that aggregates multiple counterparties), demote to the appropriate inferred flag rather than fabricate disaggregation.

## When a single arc carries multiple flags across history

The flag is per (arc, period). Arc X-to-Y for 2007-Q2 may be `SECTORAL_DISAGGREGATED` (NAIC Schedule S wasn't structured the same way then) while the same arc for 2024-Q4 is `DIRECT_MEASURED` (modern Schedule S has it). This is normal. Visualization should color-code the flag per cell, not per series.

## Downstream consumers

- **Conservation checker** treats `DIRECT_MEASURED` and `DOUBLE_ENTRY_INFERRED` as the rhs constants in Laws 1–4. Other flags are variables to be solved.
- **Bracket computation** is meaningful only for `SECTORAL_DISAGGREGATED` arcs (where ME and MD differ). For other flags, ME = MD = direct/inferred value.
- **Cascade simulator** treats arc values as point estimates but propagates uncertainty by running the cascade twice (once with ME values, once with MD) and reporting the cascade-outcome bracket.
- **Visualization** color-codes flags: green = `DIRECT_MEASURED`, light green = `DOUBLE_ENTRY_INFERRED`, yellow = `MARGINAL_INFERRED`, orange = `SECTORAL_DISAGGREGATED`, red = `PROXY`/`MODEL_ESTIMATE`, gray = `UNOBSERVED`.

## What not to do

- Do not silently default a missing arc to zero. That violates Law 2 (the issuer side won't agree) and erases the gap from view. Use `UNOBSERVED`.
- Do not promote a flag (e.g., upgrade `PROXY` to `DIRECT_MEASURED`) without re-acquiring the underlying data and re-running the fetcher.
- Do not invent new flags. The seven flags are the project's epistemic taxonomy. If a new data situation doesn't fit, the answer is to extend the documentation explaining how it maps to an existing flag — not to add an eighth.
