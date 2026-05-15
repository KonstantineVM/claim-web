# CLAIM-WEB Harness for Claude Code

This is a Claude Code harness for executing the CLAIM-WEB project autonomously over a 30-month delivery window. The harness encodes the project's plan as Claude Code primitives — CLAUDE.md, skills, subagents, slash commands, hooks, and rules — so that a Claude Code instance running inside this directory can pick up the project, find its state, and make progress with minimal human steering.

## What this harness is

A Claude Code harness is not application code. It is the *operating environment* that surrounds Claude Code so that the model can work autonomously on a long-horizon project. Anthropic's research post "[Long-running Claude for scientific computing](https://www.anthropic.com/research/long-running-Claude)" describes the canonical pattern: CLAUDE.md as project memory, a progress file as portable long-term memory across sessions, a test oracle so the agent knows whether it is making progress, git as the coordination layer, and orchestration patterns (Ralph loop, /loop command) to prevent agentic laziness on multi-day tasks. This harness instantiates that pattern for CLAIM-WEB specifically.

## What gets delivered

The CLAIM-WEB project plan (see `docs/CLAIM_WEB_PROJECT_PLAN.md` once installed) targets:

- A solved from-whom-to-whom financial network for the U.S. life insurance regulatory-arbitrage system, quarterly from 2000-Q1 through current
- Maximum-entropy and minimum-density network reconstruction with explicit uncertainty bracketing (Anand-Craig-von Peter 2015)
- Eisenberg-Noe clearing-vector cascade simulation with Cont-Schaanning fire-sale extension and Coen-Lepore-Schaanning multi-constraint binding
- Historical retrodiction of the 2007 XFABS run, 2008 AIG securities-lending collapse, and March 2020 prime-MMF / repo stress
- Peer-reviewed publication in a top-5 finance journal, interactive web product, open-source dataset and code

## How the harness works

```
The harness layers:

┌─────────────────────────────────────────────────────────────────┐
│ CLAUDE.md          standing project facts (lives in every session)│
│ docs/              the project plan and methodology references   │
│ .claude/rules/     loadable rules per topic, paths-conditional   │
│ .claude/skills/    invocable workflows for repeated tasks        │
│ .claude/agents/    isolated subagent contexts for heavy work     │
│ .claude/commands/  slash commands as human/agent entry points    │
│ .claude/hooks/     deterministic enforcement at lifecycle events │
│ .claude/settings.json hooks registration                         │
│ scripts/           the shell scripts hooks and commands call     │
│ CHANGELOG.md       lab-notebook progress memory across sessions  │
│ TODO.md            current-state task list, re-injected periodically│
└─────────────────────────────────────────────────────────────────┘
```

A new Claude Code session starts here, reads CLAUDE.md, sees the rules and skills available, and proceeds. The hooks enforce safety and consistency invariants automatically. The slash commands provide explicit entry points for high-value workflows. The subagents handle context-heavy work without polluting the main session.

## Installation

1. Place this directory at the project root where `claimweb/` (the Python package) lives or will live.
2. Run `bash scripts/setup.sh` to install hook dependencies and verify the environment.
3. Start Claude Code in that directory.
4. The first session should run `/claimweb-bootstrap` which initializes the project state.

## Repository structure expected at the project root

After full deployment, the repository should look like:

```
/path/to/claimweb-repo/
├── README.md                      (this file)
├── CLAUDE.md                      (Claude Code project memory)
├── CHANGELOG.md                   (progress log)
├── TODO.md                        (current-state task list)
├── .claude/                       (Claude Code configuration)
│   ├── settings.json
│   ├── skills/
│   ├── agents/
│   ├── commands/
│   ├── hooks/
│   └── rules/
├── scripts/                       (shell scripts called by hooks/commands)
├── docs/                          (project plan, methodology, references)
├── claimweb/                      (the Python package being built)
│   ├── fetchers/
│   ├── reconstruct/
│   ├── cascade/
│   └── ...
├── data/
├── notebooks/
├── tests/
└── pyproject.toml
```

The `.claude/` directory and its contents come from this harness. The `claimweb/` package is what Claude Code will build over the 30 months.

## Authoring conventions

- **CLAUDE.md is short and factual.** Target ~60 lines. Procedures go in skills.
- **Skills are auto-loaded by description match.** Write descriptions for what triggers them.
- **Subagents are for context-heavy work.** Spawning a subagent is roughly the cost of a fresh Claude session; use it whenever a task would generate large amounts of intermediate output that the main context doesn't need to retain.
- **Hooks are guarantees, not requests.** If something must happen, it goes in a hook.
- **Every commit is a verifiable unit.** Tests pass; conservation laws hold; data quality flags are present.

## Principles encoded in this harness

1. **Conservation laws are invariants, not goals.** Any output that violates Kirchhoff-style identities is a bug, enforced by hooks.
2. **Origin data only.** A hook blocks the introduction of paid-aggregator dependencies. Free, primary sources only.
3. **Every arc carries a provenance.** No arc enters the dataset without a data-quality flag.
4. **Historical validation is mandatory before forward use.** A model that fails to retrodict 2007, 2008, or 2020 is not deployed.
5. **The methodology is frozen at publication.** Subsequent changes are numbered amendments with public changelog.
6. **Git is the single source of truth for progress.** Commits are pushed; CHANGELOG and TODO are kept in sync.

## License

The harness itself is MIT-licensed and may be adapted to similar long-horizon projects.
