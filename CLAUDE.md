# CLAUDE.md — CLAIM-WEB

## What this project is

CLAIM-WEB quantifies the U.S. life-insurance regulatory-arbitrage network as a conservation circuit. Two outputs: (1) the **claim multiplier** — total financial claims layered on top of underlying real assets, quarterly 2000-Q1 through current; (2) the **breaking-point threshold** — the smallest shock at any entry node that triggers a cascade.

The full plan lives in `docs/CLAIM_WEB_PROJECT_PLAN.md`. Read it on first session and whenever picking up a new phase. The plan is authoritative; this file is its summary.

## Standing rules

- **Conservation laws are invariants.** Balance-sheet identity, double-entry consistency, Z.1 sectoral aggregates, and flow-of-funds identities are *not* targets; they are constraints. Any solved network violating them is a bug. Hooks enforce.
- **Origin data only.** No Capital IQ, Moody's CreditView, LCD, or any paid aggregator anywhere in the pipeline. SEC EDGAR, FRB Z.1, FHLB Office of Finance, NAIC state portals, BMA registers, FIO, OFR are the universe of permitted sources.
- **Every arc has a data-quality flag.** `DIRECT_MEASURED`, `MARGINAL_INFERRED`, `DOUBLE_ENTRY_INFERRED`, `SECTORAL_DISAGGREGATED`, `PROXY`, `MODEL_ESTIMATE`, or `UNOBSERVED`. No arc enters the dataset without one.
- **Both reconstruction methods run.** Maximum-entropy (Upper 2004) and minimum-density (Anand-Craig-von Peter 2015), with bracket reported per arc.
- **Historical validation gates deployment.** 2007 XFABS run, 2008 AIG sec-lending, March 2020 stress — all three must retrodict within tolerance before forward-use claims are published.
- **Commit and push after every meaningful unit of work.** Run `pytest tests/ -x -q` before every commit. Never commit code that breaks passing tests.
- **Update CHANGELOG.md and TODO.md when state changes.** CHANGELOG records what was done and what failed and why; TODO records what is next.
- **One step at a time on uncertain paths.** Ask before scope expansion. Big changes require user confirmation.

## How to work

- Read CHANGELOG.md and TODO.md at the start of every session to recover state.
- Use `/claimweb-bootstrap` if state is missing or unclear.
- For repeated workflows, look in `.claude/skills/` before reinventing.
- For context-heavy exploration (literature search, large dataset inspection, retrodiction replay), spawn a subagent — see `.claude/agents/`.
- For deterministic guardrails (conservation checks, paid-aggregator detection, pre-commit tests), they are already in `.claude/hooks/` and `.claude/settings.json` — don't re-implement.
- Skills auto-load by description match. The descriptions in `.claude/skills/*/SKILL.md` tell Claude when to invoke each.

## Key project paths

- `docs/CLAIM_WEB_PROJECT_PLAN.md` — full 1400-line plan
- `docs/REGULATORY_ARBITRAGE.md` — methodology framing
- `docs/LITERATURE.md` — annotated bibliography (derived from plan §2)
- `docs/PHASE_GATES.md` — what each phase must produce before the next begins
- `claimweb/` — the Python package being built
- `data/raw/` — content-addressed raw data archive (immutable)
- `data/normalized/` — normalized arc-fact store
- `data/output/` — solved networks per period

## Validation oracles

- **Conservation-law checker** (`scripts/check_conservation.py`): runs on every PostToolUse for files under `claimweb/` and `data/output/`. Asserts Laws 1–4 hold.
- **No-paid-aggregator guard** (`scripts/check_data_sources.sh`): runs on every PostToolUse for new files. Greps for forbidden imports / URLs.
- **Pre-commit gate** (`scripts/precommit_gate.sh`): runs full pytest, lints, and conservation checks.
- **Historical validation suite** (`pytest tests/validation/`): the three retrodiction episodes. Must pass green before any deployment claim.

## When unsure

Ask in chat. The user retains scope and strategic decisions per project plan §52. Methodology and implementation decisions: present options with rationale, recommend one, await go-ahead on anything non-trivial.
