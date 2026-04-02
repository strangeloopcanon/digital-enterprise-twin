# Next Phase Plan

This file is now a **historical note**, not the main product roadmap.

The original version of this document captured an earlier transition period when VEI was still moving toward:

- a canonical run and event spine
- visible mirror governance in Studio
- fork-from-snapshot sandbox flows
- world-state comparison across runs

Those pieces are now part of the shipped product.

## What Changed Since The Original Plan

The current codebase already includes:

- a unified run spine used by playback, snapshots, branching, and comparison
- a mirror control plane with agent registry, policy profiles, approval holds, connector status, and readable activity history
- provider-shaped gateway routes for Slack, Jira, Graph, and Salesforce with governed mirror traffic
- sandbox comparison tools including fork-from-here, snapshot pickers, and cross-run world-state diffs
- a focused `service_ops` what-if replay flow that changes named policy knobs and compares outcomes side by side

## Where To Look Instead

Use these files as the current source of truth:

- `README.md` — install, quickstart, and operator-facing product shape
- `docs/OVERVIEW.md` — product framing and mode-by-mode story
- `docs/ARCHITECTURE.md` — module boundaries and runtime shape
- `docs/SERVICE_OPS_WALKTHROUGH.md` — the canonical demo flow for mirror control and what-if replay

## Remaining Theme

The spirit of the older roadmap still holds: keep making VEI easier to ground in real company data, easier to govern, and easier to explain through clear operator flows.
