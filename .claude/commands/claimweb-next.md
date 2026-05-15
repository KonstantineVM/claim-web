---
description: Pick up the current Now item from TODO.md and begin work. Reads the relevant project-plan sections and any prior CHANGELOG entries that document failed approaches.
argument-hint: (none)
---

# /claimweb-next

Begin (or resume) work on the current "Now" item.

## What to do

1. **Read TODO.md "Now" item.** This is the single next thing to work on. If empty, escalate to the user — don't pick arbitrarily.

2. **Read all CHANGELOG entries referencing the same work area** to recover failed-approaches history. An item that mentions `[fetcher]` should prompt reading CHANGELOG entries tagged with the same fetcher; an item that mentions a specific module should prompt reading entries about that module. The point of CHANGELOG is to prevent re-attempting failed approaches.

3. **Read the relevant project-plan section.** The TODO item should reference a section number (e.g. "Per project plan §10.4"); if it doesn't, infer from the item description. Read that section in full.

4. **For data-source work (fetcher implementation):** before writing any code, spawn a subagent of type `data-source-investigator` (see `.claude/agents/data-source-investigator.md`) to characterize the data source: URL stability, format consistency across history, machine-readability, rate limits, gotchas. Get the subagent's report. Only after that, write code.

5. **For solver work (constraint compilation, reconstruction, cascade):** before writing any code, spawn a `literature-checker` subagent to verify that the planned approach matches the cited literature. Get the subagent's report. Only after that, write code.

6. **Implement.** One module, one focused session. If the work expands beyond one session's reasonable scope, stop, update TODO and CHANGELOG, and surface the scope expansion to the user.

7. **Test as you go.** Every public function gets a unit test before it's considered complete. Conservation-law-relevant functions get property-based tests via hypothesis.

8. **Update state files when done.**
   - CHANGELOG.md: append an entry. Include both what was done and any failed approaches tried during the session.
   - TODO.md: move the Now item to Done with the commit hash; promote the top "Next" item to "Now".

9. **Commit.** Run `bash scripts/precommit_gate.sh`. If it passes, commit and push.

## What not to do

- Do not begin work on something other than the Now item without first updating TODO.md and getting user confirmation.
- Do not skip the subagent step on first-implementation of a data source or solver. The context isolation matters — these explorations can be 100+ tool calls each, and bloating the main context with them ruins subsequent sessions.
- Do not commit code that breaks tests. The Stop hook will catch this but it's faster to catch yourself.

## Escalation

If at any point you discover that the Now item is ill-specified, depends on a missing prerequisite, or contradicts the project plan, stop and surface to the user. Do not paper over ambiguity.
