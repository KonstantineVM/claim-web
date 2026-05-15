---
description: Decimal-arithmetic discipline for any code touching dollar amounts. Conservation laws are sensitive to floating-point error; this rule is mandatory across the project.
paths:
  - claimweb/**
  - scripts/check_conservation.py
  - tests/**
---

# Decimal arithmetic — mandatory

The four conservation laws (project plan §1.1) accumulate floating-point error across nodes, arcs, and periods. By the time error reaches the cascade simulator it can flip default/no-default classifications. The fix is to use `Decimal` everywhere dollar amounts are handled.

## Rules

1. **Every dollar quantity is a `Decimal`.** Not `float`, not `int`. Use `decimal.Decimal` from the standard library.

2. **Decimal precision is set globally.** In `claimweb/__init__.py`:

   ```python
   from decimal import getcontext, ROUND_HALF_EVEN
   getcontext().prec = 28
   getcontext().rounding = ROUND_HALF_EVEN
   ```

   28-digit precision is the IEEE 754 decimal128 standard and more than sufficient for dollar amounts up to the global GDP scale.

3. **Construct Decimals from strings, not floats.** `Decimal("123.45")`, never `Decimal(123.45)`. Constructing from a float captures the float's representation error.

4. **Unit convention: millions of USD.** `dollar_amount_millions: Decimal`. Every fetcher converts to this unit at the parser. Every constraint, solver, and cascade module assumes this unit. The convention is documented in the `fetcher-author` skill and enforced by the `ArcFact` schema.

5. **Tolerance comparisons use Decimal.** Never `abs(x - y) < 1e-6` on Decimals (the literal is a float). Use `abs(x - y) < Decimal("0.000001")`.

6. **DataFrame columns holding dollar amounts use `pd.ArrowDtype(pa.decimal128(38, 6))`** for the parquet round-trip to preserve the precision. Not `float64`.

7. **JSON serialization of Decimals.** When writing JSON outputs, serialize Decimals as strings (`json.dumps(amount, default=str)`) to preserve precision across the JSON boundary. Reading back: `Decimal(value_string)`.

## Anti-patterns that violate this rule

- `sum([arc.amount for arc in arcs])` — works in modern Python because Decimal supports `sum`, but the initial value defaults to `int(0)`. Use `sum(amounts, start=Decimal(0))` to be explicit.
- `numpy` arrays of Decimal — numpy stores Decimals as object arrays, which is slow and loses vectorization. For solver matrices that need numpy, convert at the boundary and document the precision loss.
- `pandas.DataFrame` operations that auto-cast to float — `df.sum()`, `df.groupby().agg()` will silently cast Decimal columns to float. Verify after any aggregation.
- Comparing Decimal to numeric literals — `amount > 1000` works but coerces; `amount > Decimal("1000")` is explicit and safer.

## Where Decimal is not required

- Iteration counters, indices, lengths — `int` is correct
- Probabilities, ratios, log-likelihoods inside solver internals — `float` is fine because the precision loss doesn't propagate to dollar amounts (the dollar amounts are reconstructed from the solver's variable values at the boundary)
- Visualization values — `float` is fine; visualizations don't need conservation-grade precision

## How this rule interacts with cvxpy / scipy.optimize

Convex solvers operate on `float` matrices. The protocol:
1. Compile the constraint matrix in `Decimal` for correctness.
2. Convert to `float` at the boundary into the solver, recording the conversion in `SolverMetadata`.
3. Receive the `float` solution.
4. Round the solution at appropriate precision (typically Decimal("0.000001") on millions, i.e. dollars).
5. Re-verify Laws 1–4 hold on the rounded solution in `Decimal`. If precision loss in the float solver caused a violation, surface it; do not silently re-relax.

## Testing

Property-based tests using hypothesis with Decimal strategies:

```python
from hypothesis import given
from hypothesis.strategies import decimals

@given(decimals(min_value="0", max_value="1e9", places=2))
def test_arc_value_preserves_precision(amount):
    arc = ArcFact(..., dollar_amount_millions=amount, ...)
    # Round-trip via parquet
    df = pa.Table.from_pylist([arc.to_dict()])
    df.write_parquet("/tmp/t.parquet")
    back = ArcFact.from_dict(pa.read_table("/tmp/t.parquet").to_pylist()[0])
    assert back.dollar_amount_millions == amount  # exact, not approximate
```
