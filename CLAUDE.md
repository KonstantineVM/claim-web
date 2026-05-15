# CLAUDE.md — CLAIM-WEB

## What this project is

CLAIM-WEB quantifies the U.S. life-insurance regulatory-arbitrage network as a conservation circuit. Two outputs: (1) the **claim multiplier** — total financial claims layered on top of underlying real assets, quarterly 2000-Q1 through current; (2) the **breaking-point threshold** — the smallest shock at any entry node that triggers a cascade.

The full plan lives in `docs/CLAIM_WEB_PROJECT_PLAN.md`. Read it on first session and whenever picking up a new phase. The plan is authoritative; this file is its summary.

## Operating mode: autonomous

This repository runs in autonomous mode. The workflow per session:

1. Read CHANGELOG.md and TODO.md to recover state.
2. Pick up the current "Now" item from TODO.md without asking.
3. Complete the item per the relevant slash command or skill.
4. Update CHANGELOG.md with a full entry (what was done, what failed, what is next).
5. Update TODO.md: move the completed item to Done; promote the top Next item to Now.
6. Run scripts/precommit_gate.sh.
7. Commit with a descriptive message; push.
8. Stop.

Each session completes one Now item. The GitHub Actions gate runs the precommit checks on the PR and auto-merges on green. No human approval is needed for merge — the gate is the gate.

## Standing rules

- **Conservation laws are invariants.** Balance-sheet identity, double-entry consistency, Z.1 sectoral aggregates, and flow-of-funds identities are *not* targets; they are constraints. Any solved network violating them is a bug. Hooks enforce.
- **Origin data only.** No Capital IQ, Moody's CreditView, LCD, or any paid aggregator anywhere in the pipeline. SEC EDGAR, FRB Z.1, FHLB Office of Finance, NAIC state portals, BMA registers, FIO, OFR are the universe of permitted sources.
- **Every arc has a data-quality flag.** `DIRECT_MEASURED`, `MARGINAL_INFERRED`, `DOUBLE_ENTRY_INFERRED`, `SECTORAL_DISAGGREGATED`, `PROXY`, `MODEL_ESTIMATE`, or `UNOBSERVED`. No arc enters the dataset without one.
- **Both reconstruction methods run.** Maximum-entropy (Upper 2004) and minimum-density (Anand-Craig-von Peter 2015), with bracket reported per arc.
- **Historical validation gates deployment.** 2007 XFABS run, 2008 AIG sec-lending, March 2020 stress — all three must retrodict within tolerance before forward-use claims are published.
- **Commit and push at the end of every session.** Run `scripts/precommit_gate.sh` first. Never commit code that breaks passing tests.
- **CHANGELOG.md and TODO.md are updated every session.** CHANGELOG records what was done and what failed and why; TODO records what is next.

## When to stop and surface to the user

Independence does not mean reckless. Stop and surface to the user only in these cases:

- **The current Now item is structurally ambiguous** — TODO.md doesn't say enough to act, and CHANGELOG and project plan don't disambiguate.
- **A historical validation that previously passed now fails** — this is a regression and requires user awareness before further work.
- **Methodology amendment is needed** — per project plan §48, substantive methodology changes require user authorization. Use the `methodology-amendment` skill; it stops at the user-confirmation step.
- **A blocked item in TODO.md is the only remaining Now-eligible work** — surface the block.
- **The precommit gate fails after good-faith effort to fix** — three iterations of trying to make it pass without success means something deeper is wrong; surface it.

In all other cases: proceed.

## How to work

- Read CHANGELOG.md and TODO.md at the start of every session to recover state.
- Use `/claimweb-bootstrap` on the very first task (creates the Python package skeleton).
- Use `/claimweb-next` for every subsequent task; it picks up the Now item.
- For repeated workflows, look in `.claude/skills/` before reinventing.
- For context-heavy exploration (literature search, large dataset inspection, retrodiction replay), spawn a subagent — see `.claude/agents/`.
- For deterministic guardrails, hooks are in `.claude/hooks/` and `.claude/settings.json` — don't re-implement.
- Skills auto-load by description match.

## Key project paths

- `docs/CLAIM_WEB_PROJECT_PLAN.md` — full plan
- `docs/REGULATORY_ARBITRAGE.md` — methodology framing
- `docs/PHASE_GATES.md` — what each phase must produce before the next begins
- `claimweb/` — the Python package being built
- `data/raw/` — content-addressed raw data archive (gitignored; immutable)
- `data/normalized/` — normalized arc-fact store
- `data/output/` — solved networks per period

## Validation oracles

- **Conservation-law checker** (`scripts/check_conservation.py`): runs on every PostToolUse for files under `claimweb/` and `data/output/`. Asserts Laws 1–4 hold.
- **No-paid-aggregator guard** (`scripts/check_data_sources.sh`): runs on every PostToolUse for new files. Greps for forbidden imports / URLs.
- **Pre-commit gate** (`scripts/precommit_gate.sh`): runs full pytest, lints, and conservation checks. The GitHub Actions workflow runs this on every PR.
- **Historical validation suite** (`pytest tests/validation/`): the three retrodiction episodes. Must pass green before any deployment claim.

## Phase gates govern transitions

`docs/PHASE_GATES.md` lists the criteria for each of the five phases. Closing a phase requires every criterion verified. The `phase-gate-closer` skill performs the verification. Phase-gate closure is one of the few user-confirmation events (per project plan §52); when ready, surface the verification results and request confirmation.
