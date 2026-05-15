---
description: Run the autonomous Ralph-style loop. Keep working on the current Now item until a completion-promise is announced or max iterations reached. Use sparingly — best when the work is well-scoped and the test oracle is solid.
argument-hint: [max-iterations] [completion-promise]
---

# /claimweb-loop

Run the autonomous loop pattern from https://www.anthropic.com/research/long-running-Claude.

## Arguments

- `[max-iterations]`: default 10. The loop terminates after this many iterations regardless of state.
- `[completion-promise]`: the literal string the agent must emit to declare done. Default: `CLAIMWEB-PHASE-DONE`.

## What to do

This is a long-running pattern, not a single response. Treat it as a sequence:

1. **Verify preconditions.** The current Now item must be well-scoped. If the Now item is broad or exploratory (e.g. "investigate the BMA register format"), the loop is not appropriate — use `/claimweb-next` instead. Loops are for tasks with clear completion criteria.

2. **State the completion criterion explicitly.** Before iteration 1, write to the chat:
   > Loop starting. Now item: {item}. Completion criterion: {criterion}. Max iterations: {N}. Completion promise: {string}.
   This makes the criterion visible and prevents drift.

3. **Iterate.** Each iteration:
   - Read CHANGELOG.md and TODO.md for current state.
   - Make progress on the current sub-step.
   - Run the relevant tests / conservation checks.
   - If criterion is met, emit the completion promise string and stop.
   - If not met, identify the next sub-step.
   - At end of iteration, append a short CHANGELOG entry (1–3 lines, not a full entry — the full entry comes at the loop's end).

4. **Sub-iteration discipline.** Each iteration must produce a verifiable artifact: a passing test, a green conservation check, a new function with its docstring, a new file. An iteration that produces no verifiable artifact is a failed iteration; count it and continue, but if 3 consecutive iterations fail, stop and surface to user.

5. **End-of-loop housekeeping.** When the completion-promise emits (success) or max-iterations reached (timeout):
   - Append a full CHANGELOG entry summarizing the loop: iterations consumed, what was achieved, what (if anything) was left undone.
   - Update TODO.md.
   - Run `bash scripts/precommit_gate.sh`.
   - Commit and push.
   - If timeout (not success), surface to user: "Loop terminated at max iterations. Item is not complete. Here is what remains: ..."

## What not to do

- Do not silently extend max-iterations. If the loop times out, that is the user's signal.
- Do not skip iteration-level CHANGELOG appendings; without them, a failed run is unrecoverable.
- Do not run this on tasks that don't have a clear completion criterion. The Ralph loop's value is in the for-loop structure; without a criterion, the loop just wastes iterations.
- Do not commit at every iteration. Commit at the loop's end. Each iteration is a sub-step, not a unit-of-work.

## Example invocations

- `/claimweb-loop 20 FHLB-FETCHER-COMPLETE` — implement the FHLB fetcher to completion, declare done with that string.
- `/claimweb-loop 10 VALIDATION-EP1-PASS` — re-parameterize until Episode 1 validation passes.
