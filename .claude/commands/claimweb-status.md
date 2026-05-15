---
description: Report the current state of the CLAIM-WEB project — phase, recent progress, current Now item, blocked items, and any validation status.
argument-hint: (none)
---

# /claimweb-status

Produce a concise status report.

## What to do

Compose a single status report covering:

1. **Phase** — read `docs/PHASE_GATES.md` and identify which phase (1–5 per project plan §35) the project is currently in, and which gate criteria remain open.

2. **Now item** — read the top of `TODO.md` and report the current "Now" task. If "Now" is empty, that itself is the headline.

3. **Recent progress** — read the most recent 2–3 CHANGELOG entries and summarize what was just done (one sentence each).

4. **Blocked items** — read the "Blocked" section of TODO.md and list anything waiting on user decision or external input.

5. **Validation status** — if `tests/validation/` contains test files, attempt to run them quickly (timeout 60s) with `pytest tests/validation/ -x --co -q` (collect-only) and report whether the three historical episodes (2007 XFABS, 2008 AIG, 2020 stress) have test files; if any of them have been run recently and have logged retrodiction outputs, report the current best retrodiction errors.

6. **Git state** — branch, uncommitted changes summary (file count only, no diff content), last 3 commit messages.

7. **Hooks active** — read `.claude/settings.json` and list the registered hook events.

Format as a short report, ~30–60 lines total. No deep dive — that's what `/claimweb-deep-dive` would be for (not yet implemented).

## What not to do

- Do not modify any files. This is read-only.
- Do not start work on the Now item. The user asked for status, not action.
- Do not paste full file contents — summarize.
