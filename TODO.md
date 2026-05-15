# TODO — CLAIM-WEB

Current-state task list. Read this at the start of every session. Update after every meaningful unit of work.

## How this file works

- The top of the file is "Now" — the single next thing to work on.
- "Next" is the small queue (3–5 items) of what comes after.
- "Backlog" is everything else, grouped by phase from the project plan.
- "Done" is a short rolling log of recently completed items (move from "Now" to "Done" as work finishes; prune monthly).
- "Blocked" lists anything waiting on external input (user decision, data source change, etc.) with why.

The `/claimweb-status` slash command reads this file and reports back; the `/claimweb-next` slash command picks up the "Now" item and begins work.

---

## Now

- **[bootstrap]** Initialize the repository structure: create `claimweb/` Python package skeleton (pyproject.toml, package directories per project plan §18), run `bash scripts/setup.sh`, verify hooks fire by making a trivial test edit.

## Next

1. **[fetcher]** Implement `claimweb.fetchers.fhlb_combined`: download the most recent FHLB Office of Finance Combined Financial Report, extract the structured tables (total advances, advance composition, member-type breakdown). Per project plan §10.4. Estimate: 1–2 sessions.
2. **[constraints]** Implement `claimweb.constraints.kcl`: the balance-sheet identity checker with property-based tests via hypothesis. The function must accept a node's arc set and return (holds: bool, residual: float, diagnostic: dict). Per project plan §13 Phase A and §21. Estimate: 1 session.
3. **[fetcher]** Implement `claimweb.fetchers.z1`: pull the FRB Z.1 quarterly release tables L.116, L.121, L.207, L.208, L.211, L.226, L.227. Provides Law 3 sectoral constraints. Per project plan §10.1. Estimate: 1–2 sessions.
4. **[reconstruction]** First end-to-end single-arc reconstruction: FHLB → U.S. life insurer members for 2024-Q4, with conservation-law check and data-quality flag. This is the project plan's first-week-actions concrete deliverable.

## Backlog

### Phase 1 — Foundation (months 1–6)

Per project plan §35.

- Finalize methodology document (extract from plan §1, expand with formal proofs of constraint-satisfiability)
- Build remaining fetcher infrastructure for 2024-Q4 reference quarter end-to-end
- Acquire data for 2024-Q4 end-to-end
- Build network reconstruction (maximum-entropy and minimum-density both) for 2024-Q4
- Verify Laws 1–4 hold on the reference quarter
- Initial Sankey visualization for 2024-Q4

### Phase 2 — Historical reconstruction (months 7–12)

- Extend fetchers backward to 2000-Q1
- Solve the network at each quarterly period
- Build the cascade simulator (Eisenberg-Noe core, then fire-sale extension, then multi-constraint binding)
- Run baseline cascade scenarios for each period
- First historical-retrodiction attempts (2007 XFABS, 2008 AIG, 2020 stress)

### Phase 3 — Validation and methodology refinement (months 13–18)

- Iterate on retrodictions until all three pass
- Build the visualization layer (Sankey, node-link, cascade-DAG)
- Build the interactive web product MVP
- Draft the methodology paper

### Phase 4 — External review (months 19–24)

- Pre-submission review by three external experts
- Address review comments
- Industry and regulator briefings
- Submit to first-choice journal

### Phase 5 — Publication and launch (months 25–30)

- Peer-review rounds
- Web product polish
- Press launch
- Open-source release
- Conference presentations

## Done

<!-- Move completed items here. Keep ~30 days, prune monthly. -->

## Blocked

<!-- Items waiting on user decision or external input. -->

---

## Conventions

- Tag items with `[fetcher]`, `[constraints]`, `[reconstruction]`, `[cascade]`, `[validation]`, `[visualization]`, `[docs]`, `[infra]`, `[bootstrap]` for filtering.
- Estimate is optional; if used, in sessions, not hours.
- When moving an item to "Done", record the commit hash and the CHANGELOG entry that documents it.
- Never delete a "Blocked" item — resolve it or move to "Done"/"Backlog" with a note.
